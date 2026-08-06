from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.chat import ChatType, TelegramChat
from app.models.message import TelegramMessage
from app.services.media_access import (
    create_media_download_token,
    decode_media_download_token,
)
from app.services.media_download_service import DownloadedMedia
from app.services.media_download_service import download_telegram_media
from app.services.telegram_links import build_telegram_message_url


def test_build_telegram_message_url_prefers_public_username():
    assert (
        build_telegram_message_url(
            chat_type=ChatType.CHANNEL,
            telegram_chat_id=-1001234567890,
            username="wai_channel",
            message_id=42,
        )
        == "https://t.me/wai_channel/42"
    )


def test_build_telegram_message_url_supports_private_channel_links():
    assert (
        build_telegram_message_url(
            chat_type=ChatType.SUPERGROUP,
            telegram_chat_id=-1001234567890,
            username=None,
            message_id=42,
        )
        == "https://t.me/c/1234567890/42"
    )


def test_build_telegram_message_url_returns_none_for_unaddressable_private_chat():
    assert (
        build_telegram_message_url(
            chat_type=ChatType.PRIVATE,
            telegram_chat_id=123456789,
            username=None,
            message_id=42,
        )
        is None
    )


def test_media_download_token_round_trips_and_expires():
    user_id = uuid4()
    chat_id = uuid4()
    token = create_media_download_token(
        user_id=user_id,
        chat_id=chat_id,
        telegram_message_id=42,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    payload = decode_media_download_token(token)

    assert payload.user_id == user_id
    assert payload.chat_id == chat_id
    assert payload.telegram_message_id == 42


def test_media_download_token_rejects_tampering():
    token = create_media_download_token(
        user_id=uuid4(),
        chat_id=uuid4(),
        telegram_message_id=42,
    )

    with pytest.raises(ValueError, match="invalid media download token"):
        decode_media_download_token(token + "tampered")


@pytest.mark.asyncio
async def test_download_service_fetches_original_telegram_media(
    db_session, test_user, tmp_path
):
    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=54321,
        chat_type=ChatType.PRIVATE,
        title="Media chat",
    )
    db_session.add(chat)
    await db_session.flush()

    telegram_message = MagicMock()
    telegram_message.media = object()
    telegram_message.file = MagicMock(mime_type="audio/ogg", name=None)
    client = AsyncMock()
    client.get_messages.return_value = telegram_message
    client.download_media.side_effect = lambda _message, file: _write_file(file)
    destination = tmp_path / "source"

    with (
        patch(
            "app.services.media_download_service.get_client",
            new_callable=AsyncMock,
            return_value=client,
        ),
        patch(
            "app.services.media_download_service._resolve_chat_entity",
            new_callable=AsyncMock,
            return_value="peer",
        ),
    ):
        result = await download_telegram_media(
            db_session,
            test_user.id,
            chat.id,
            42,
            destination,
        )

    assert result.path == destination
    assert result.file_name == "telegram-media.oga"
    assert result.mime_type == "audio/ogg"
    assert result.file_size == len(b"media")
    client.get_messages.assert_awaited_once_with("peer", ids=42)
    client.download_media.assert_awaited_once_with(
        telegram_message, file=str(destination)
    )
    client.disconnect.assert_awaited_once()


def _write_file(path: str) -> str:
    Path(path).write_bytes(b"media")
    return path


@pytest.mark.asyncio
async def test_content_response_exposes_signed_media_url(
    auth_client,
    db_session,
    test_user,
):
    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=-1001234567890,
        chat_type=ChatType.CHANNEL,
        title="Media channel",
        username="media_channel",
    )
    db_session.add(chat)
    await db_session.flush()
    message = TelegramMessage(
        chat_id=chat.id,
        telegram_message_id=42,
        text="Caption https://example.com",
        has_media=True,
        media_type="video",
        media_file_name="clip.mp4",
        media_mime_type="video/mp4",
        media_file_size=123,
        sent_at=datetime.now(UTC),
    )
    db_session.add(message)
    await db_session.flush()

    response = await auth_client.get(f"/api/v1/chats/{chat.id}/messages/42/content")

    assert response.status_code == 200
    payload = response.json()
    assert payload["telegram_message_url"] == "https://t.me/media_channel/42"
    media_url = payload["media_download_url"]
    parsed = urlparse(media_url)
    assert parsed.path.endswith(f"/chats/{chat.id}/messages/42/media")
    assert parse_qs(parsed.query).get("token")


@pytest.mark.asyncio
async def test_signed_media_url_downloads_binary_without_bearer(
    auth_client,
    client,
    db_session,
    test_user,
):
    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=54321,
        chat_type=ChatType.PRIVATE,
        title="Media chat",
    )
    db_session.add(chat)
    await db_session.flush()
    message = TelegramMessage(
        chat_id=chat.id,
        telegram_message_id=43,
        has_media=True,
        media_type="audio",
        media_file_name="voice.ogg",
        media_mime_type="audio/ogg",
        sent_at=datetime.now(UTC),
    )
    db_session.add(message)
    await db_session.flush()

    content_response = await auth_client.get(
        f"/api/v1/chats/{chat.id}/messages/43/content"
    )
    media_url = content_response.json()["media_download_url"]

    async def fake_download(
        _db, _user_id, _chat_id, _message_id, destination, **_kwargs
    ):
        destination.write_bytes(b"audio fixture")
        return DownloadedMedia(
            path=destination,
            file_name="voice.ogg",
            mime_type="audio/ogg",
            file_size=13,
        )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("app.api.v1.chats.download_telegram_media", fake_download)
        response = await client.get(media_url)

    assert response.status_code == 200
    assert response.content == b"audio fixture"
    assert response.headers["content-type"] == "audio/ogg"
    assert "voice.ogg" in response.headers["content-disposition"]
