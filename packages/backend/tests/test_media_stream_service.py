"""Streaming an original means nothing has to be staged before a download."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.chat import ChatType, TelegramChat
from app.models.message import TelegramMessage
from app.services.media_stream_service import (
    MediaStreamUnavailable,
    open_media_stream,
)


async def _seed(db_session, test_user, *, has_media=True):
    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=6001,
        chat_type=ChatType.PRIVATE,
        title="Stream chat",
    )
    db_session.add(chat)
    await db_session.flush()
    message = TelegramMessage(
        chat_id=chat.id,
        telegram_message_id=77,
        has_media=has_media,
        media_type="document",
        media_file_name="report.pdf",
        media_mime_type="application/pdf",
        media_file_size=2048,
        sent_at=datetime.now(UTC),
    )
    db_session.add(message)
    await db_session.flush()
    return chat, message


def _client(chunks=(b"abc", b"def"), media=object()):
    client = AsyncMock()
    client.get_messages = AsyncMock(return_value=SimpleNamespace(media=media))

    def iter_download(*_args, **_kwargs):
        async def gen():
            for chunk in chunks:
                yield chunk

        return gen()

    client.iter_download = iter_download
    client.disconnect = AsyncMock()
    return client


def _patched(client, info):
    return (
        patch(
            "app.services.media_stream_service.get_client",
            new_callable=AsyncMock,
            return_value=client,
        ),
        patch(
            "app.services.media_stream_service._resolve_chat_entity",
            new_callable=AsyncMock,
            return_value=object(),
        ),
        patch("app.services.media_stream_service.get_media_info", return_value=info),
    )


async def test_bytes_arrive_without_anything_being_staged(db_session, test_user):
    chat, _row = await _seed(db_session, test_user)
    client = _client()
    info = SimpleNamespace(
        file_name="report.pdf",
        mime_type="application/pdf",
        file_size=2048,
        media_type="document",
        duration_seconds=None,
    )

    a, b, c = _patched(client, info)
    with a, b, c:
        media, chunks = await open_media_stream(db_session, test_user.id, chat.id, 77)
        body = b"".join([chunk async for chunk in chunks])

    assert body == b"abcdef"
    assert media.file_name == "report.pdf"
    assert media.mime_type == "application/pdf"
    assert media.size_bytes == 2048
    client.disconnect.assert_awaited()


async def test_the_message_is_refetched_so_the_file_reference_is_fresh(
    db_session, test_user
):
    """A stored Telegram file reference goes stale, so it cannot be reused."""
    chat, _row = await _seed(db_session, test_user)
    client = _client()
    info = SimpleNamespace(
        file_name=None,
        mime_type=None,
        file_size=None,
        media_type="document",
        duration_seconds=None,
    )

    a, b, c = _patched(client, info)
    with a, b, c:
        media, chunks = await open_media_stream(db_session, test_user.id, chat.id, 77)
        [chunk async for chunk in chunks]

    client.get_messages.assert_awaited_once()
    # Falls back to what the message row knows when Telegram tells us nothing.
    assert media.file_name == "report.pdf"
    assert media.mime_type == "application/pdf"


async def test_a_deleted_source_is_reported_not_streamed(db_session, test_user):
    chat, _row = await _seed(db_session, test_user)
    client = _client(media=None)
    client.get_messages = AsyncMock(return_value=SimpleNamespace(media=None))

    a, b, c = _patched(client, None)
    with a, b, c, pytest.raises(MediaStreamUnavailable, match="deleted"):
        await open_media_stream(db_session, test_user.id, chat.id, 77)

    client.disconnect.assert_awaited(), "a refused stream must not leak a connection"


async def test_a_message_without_media_is_refused(db_session, test_user):
    chat, _row = await _seed(db_session, test_user, has_media=False)

    with pytest.raises(MediaStreamUnavailable, match="no media"):
        await open_media_stream(db_session, test_user.id, chat.id, 77)


async def test_another_users_message_is_not_streamable(db_session, test_user):
    from uuid import uuid4

    chat, _row = await _seed(db_session, test_user)

    with pytest.raises(MediaStreamUnavailable, match="not found"):
        await open_media_stream(db_session, uuid4(), chat.id, 77)


async def test_an_abandoned_download_still_closes_the_connection(db_session, test_user):
    """A caller that walks away mid-file must not strand a Telegram client."""
    chat, _row = await _seed(db_session, test_user)
    client = _client(chunks=(b"a", b"b", b"c"))
    info = SimpleNamespace(
        file_name="report.pdf",
        mime_type="application/pdf",
        file_size=3,
        media_type="document",
        duration_seconds=None,
    )

    a, b, c = _patched(client, info)
    with a, b, c:
        _media, chunks = await open_media_stream(db_session, test_user.id, chat.id, 77)
        assert await anext(chunks) == b"a"
        await chunks.aclose()

    client.disconnect.assert_awaited()


@pytest.mark.parametrize(
    "header, expected",
    [
        (None, 0),
        ("bytes=0-", 0),
        ("bytes=1024-", 1024),
        ("bytes=1024-2047", 1024),
        ("bytes=-500", 0),
        ("nonsense", 0),
    ],
)
def test_a_range_header_becomes_a_resume_offset(header, expected):
    from starlette.datastructures import Headers

    from app.api.v1.chats import _requested_offset

    request = SimpleNamespace(headers=Headers({"range": header} if header else {}))
    assert _requested_offset(request) == expected


async def test_a_ranged_request_answers_206_from_the_offset(
    auth_client, db_session, test_user
):
    """Resuming a large download must not restart it from zero."""
    from app.services.media_stream_service import StreamableMedia

    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=6100,
        chat_type=ChatType.PRIVATE,
        title="Range chat",
    )
    db_session.add(chat)
    await db_session.flush()
    db_session.add(
        TelegramMessage(
            chat_id=chat.id,
            telegram_message_id=88,
            has_media=True,
            media_type="video",
            media_file_size=1000,
            sent_at=datetime.now(UTC),
        )
    )
    await db_session.flush()

    async def chunks():
        yield b"tail"

    captured = {}

    async def fake_open(_db, _uid, _chat, _tmid, *, offset=0):
        captured["offset"] = offset
        return (
            StreamableMedia(file_name="v.mp4", mime_type="video/mp4", size_bytes=1000),
            chunks(),
        )

    with patch("app.api.v1.chats.open_media_stream", side_effect=fake_open):
        response = await auth_client.get(
            f"/api/v1/chats/{chat.id}/messages/88/media",
            headers={"Range": "bytes=996-"},
        )

    assert captured["offset"] == 996
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 996-999/1000"
    assert response.headers["content-length"] == "4"
    assert response.content == b"tail"
