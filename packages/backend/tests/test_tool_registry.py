from datetime import UTC, datetime
from unittest.mock import patch

from app.core.security import compute_api_key_prefix, get_key_hint, hash_api_key
from app.models.api_key import ApiKey
import pytest
from sqlalchemy import select

from app.models.chat import ChatType, TelegramChat
from app.models.media import (
    MediaObject,
    MediaObjectStatus,
    MediaStage,
    TranscriptSegment,
)
from app.models.message import MediaProcessingStatus, TelegramMessage
from app.services.tool_registry import ToolInputError, execute_data_tool


async def _seed(db_session, test_user):
    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=-1001234567890,
        chat_type=ChatType.CHANNEL,
        title="Tool chat",
        username="tool_chat",
    )
    db_session.add(chat)
    await db_session.flush()
    message = TelegramMessage(
        chat_id=chat.id,
        telegram_message_id=42,
        text="Caption",
        has_media=True,
        media_type="audio",
        media_file_name="meeting.ogg",
        media_mime_type="audio/ogg",
        media_file_size=120,
        content_text="abcdefghij",
        content_summary="Summary",
        media_processing_status=MediaProcessingStatus.READY,
        hidden_urls=["https://hidden.example"],
        reply_to_message_id=41,
        sent_at=datetime.now(UTC),
    )
    db_session.add(message)
    await db_session.flush()
    db_session.add(
        MediaObject(
            user_id=test_user.id,
            message_id=message.id,
            cache_key="1" * 64,
            relative_path="11/cache/original.ogg",
            file_name="meeting.ogg",
            mime_type="audio/ogg",
            size_bytes=120,
            sha256="2" * 64,
            byte_offset=120,
            status=MediaObjectStatus.READY,
            stage=MediaStage.COMPLETE,
        )
    )
    db_session.add_all(
        [
            TranscriptSegment(
                message_id=message.id,
                sequence=index,
                start_ms=index * 1000,
                end_ms=(index + 1) * 1000,
                speaker="A",
                confidence=0.9,
                language="ru",
                text=f"segment {index}",
            )
            for index in range(3)
        ]
    )
    await db_session.flush()
    return chat, message


async def test_shared_tools_expose_metadata_content_segments_and_download(
    db_session, test_user
):
    chat, message = await _seed(db_session, test_user)
    locator = {"chat_id": str(chat.id), "telegram_message_id": 42}

    metadata = await execute_data_tool(db_session, test_user.id, "get_message", locator)
    content = await execute_data_tool(
        db_session,
        test_user.id,
        "get_message_content",
        {**locator, "cursor": 0, "limit_chars": 1000},
    )
    segments = await execute_data_tool(
        db_session,
        test_user.id,
        "get_transcript_segments",
        {**locator, "limit": 2},
    )
    download = await execute_data_tool(
        db_session, test_user.id, "download_media", locator
    )

    assert metadata["id"] == str(message.id)
    assert metadata["hidden_urls"] == ["https://hidden.example"]
    assert metadata["reply_to_message_id"] == 41
    assert content["content_text"] == "abcdefghij"
    assert content["has_more"] is False
    assert len(segments["segments"]) == 2
    assert segments["has_more"] is True
    assert segments["next_cursor"] == 2
    assert download["media_sha256"] == "2" * 64
    assert "token=" in download["media_download_url"]
    assert download["telegram_message_url"] == "https://t.me/tool_chat/42"


async def test_tools_api_lists_all_shared_data_tools(auth_client):
    response = await auth_client.get("/api/v1/tools")

    assert response.status_code == 200
    names = {tool["name"] for tool in response.json()["tools"]}
    assert names == {
        "search_messages",
        "get_message",
        "prepare_media",
        "download_media",
        "get_message_content",
        "get_transcript_segments",
        "get_data_status",
    }


async def test_shared_registry_rejects_a_deactivated_user(db_session, test_user):
    test_user.is_active = False
    await db_session.flush()

    with pytest.raises(ToolInputError, match="inactive"):
        await execute_data_tool(db_session, test_user.id, "get_data_status", {})


async def test_prepare_media_tool_does_not_duplicate_pending_dispatch(
    db_session,
    test_user,
):
    chat, message = await _seed(db_session, test_user)
    media_object = (
        await db_session.execute(
            select(MediaObject).where(MediaObject.message_id == message.id)
        )
    ).scalar_one()
    message.media_processing_status = None
    media_object.status = MediaObjectStatus.FAILED
    media_object.relative_path = None
    media_object.sha256 = None
    locator = {"chat_id": str(chat.id), "telegram_message_id": 42}

    with patch("app.tasks.media_tasks.enqueue_media_processing") as enqueue:
        first = await execute_data_tool(
            db_session,
            test_user.id,
            "prepare_media",
            locator,
        )
        second = await execute_data_tool(
            db_session,
            test_user.id,
            "prepare_media",
            locator,
        )

    assert first["enqueued"] is True
    assert second["enqueued"] is False
    enqueue.assert_called_once_with([message.id])


async def test_read_only_api_key_cannot_start_media_processing(
    client, db_session, test_user
):
    raw_key = "wai_read_only_media_key_abcdefghijklmnopqrstuvwxyz"
    db_session.add(
        ApiKey(
            user_id=test_user.id,
            name="Read only",
            key_hash=hash_api_key(raw_key),
            key_prefix=compute_api_key_prefix(raw_key),
            key_hint=get_key_hint(raw_key),
            scopes="read",
            is_active=True,
        )
    )
    await db_session.flush()
    headers = {"Authorization": f"Bearer {raw_key}"}

    discovery = await client.get("/api/v1/tools", headers=headers)
    mutation = await client.post(
        "/api/v1/tools/prepare_media",
        headers=headers,
        json={"arguments": {}},
    )

    assert discovery.status_code == 200
    assert mutation.status_code == 403
