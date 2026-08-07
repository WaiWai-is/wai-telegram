from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.models.chat import ChatType, TelegramChat
from app.models.media import MediaObject, MediaObjectStatus, MediaStage
from app.models.message import TelegramMessage
from app.services.media_access import (
    create_media_download_token,
    decode_media_download_token,
)
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
async def test_content_response_exposes_signed_media_url(
    auth_client,
    db_session,
    test_user,
    tmp_path,
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
    relative_path = "aa/cache/original.mp4"
    cached_path = tmp_path / relative_path
    cached_path.parent.mkdir(parents=True)
    cached_path.write_bytes(b"video")
    db_session.add(
        MediaObject(
            user_id=test_user.id,
            message_id=message.id,
            cache_key="a" * 64,
            relative_path=relative_path,
            file_name="clip.mp4",
            mime_type="video/mp4",
            size_bytes=5,
            sha256="b" * 64,
            byte_offset=5,
            status=MediaObjectStatus.READY,
            stage=MediaStage.COMPLETE,
        )
    )
    await db_session.flush()

    with patch("app.services.media_cache_service.settings") as cache_settings:
        cache_settings.media_root = tmp_path
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
    tmp_path,
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
    relative_path = "cc/cache/original.ogg"
    cached_path = tmp_path / relative_path
    cached_path.parent.mkdir(parents=True)
    cached_path.write_bytes(b"audio fixture")
    db_session.add(
        MediaObject(
            user_id=test_user.id,
            message_id=message.id,
            cache_key="c" * 64,
            relative_path=relative_path,
            file_name="voice.ogg",
            mime_type="audio/ogg",
            size_bytes=13,
            sha256="d" * 64,
            byte_offset=13,
            status=MediaObjectStatus.READY,
            stage=MediaStage.COMPLETE,
        )
    )
    await db_session.flush()

    with patch("app.services.media_cache_service.settings") as cache_settings:
        cache_settings.media_root = tmp_path
        content_response = await auth_client.get(
            f"/api/v1/chats/{chat.id}/messages/43/content"
        )
        media_url = content_response.json()["media_download_url"]
        response = await client.get(media_url)

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["content-type"] == "audio/ogg"
    assert "voice.ogg" in response.headers["content-disposition"]
    assert response.headers["x-accel-redirect"].endswith(relative_path)
    assert response.headers["etag"] == f'"{"d" * 64}"'
    assert "accept-ranges" not in response.headers


@pytest.mark.asyncio
async def test_signed_media_url_stops_working_after_user_deactivation(
    auth_client,
    client,
    db_session,
    test_user,
    tmp_path,
):
    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=54322,
        chat_type=ChatType.PRIVATE,
        title="Deactivated media",
    )
    db_session.add(chat)
    await db_session.flush()
    message = TelegramMessage(
        chat_id=chat.id,
        telegram_message_id=44,
        has_media=True,
        media_type="document",
        media_file_name="archive.pdf",
        media_mime_type="application/pdf",
        sent_at=datetime.now(UTC),
    )
    db_session.add(message)
    await db_session.flush()
    relative_path = "ee/cache/original.pdf"
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"pdf")
    db_session.add(
        MediaObject(
            user_id=test_user.id,
            message_id=message.id,
            cache_key="e" * 64,
            relative_path=relative_path,
            file_name="archive.pdf",
            mime_type="application/pdf",
            size_bytes=3,
            sha256="f" * 64,
            byte_offset=3,
            status=MediaObjectStatus.READY,
            stage=MediaStage.COMPLETE,
        )
    )
    await db_session.flush()

    with patch("app.services.media_cache_service.settings") as cache_settings:
        cache_settings.media_root = tmp_path
        content_response = await auth_client.get(
            f"/api/v1/chats/{chat.id}/messages/44/content"
        )
    media_url = content_response.json()["media_download_url"]
    test_user.is_active = False
    await db_session.flush()

    response = await client.get(media_url)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_uncached_content_requires_prepare(auth_client, db_session, test_user):
    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=54323,
        chat_type=ChatType.PRIVATE,
        title="Uncached",
    )
    db_session.add(chat)
    await db_session.flush()
    db_session.add(
        TelegramMessage(
            chat_id=chat.id,
            telegram_message_id=45,
            has_media=True,
            media_type="video",
            sent_at=datetime.now(UTC),
        )
    )
    await db_session.flush()

    response = await auth_client.get(f"/api/v1/chats/{chat.id}/messages/45/content")

    assert response.status_code == 200
    assert response.json()["media_download_url"] is None
    assert "prepare_media" in response.json()["next_action"]
