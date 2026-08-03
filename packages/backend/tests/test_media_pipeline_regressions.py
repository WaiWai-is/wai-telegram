import asyncio
import inspect
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.listener.main import TelegramListener
from app.models.message import TelegramMessage
from app.services.media_content_service import MediaInfo
from app.services.media_processing_service import (
    ClaimedMediaMessage,
    MediaDownloadError,
    _download_telegram_media,
    _get_media_client,
    disconnect_media_clients,
)
from app.services.sync_service import _media_values


def _message_row(telegram_message_id: int, media_values: dict) -> dict:
    return {
        "chat_id": uuid4(),
        "telegram_message_id": telegram_message_id,
        "text": None,
        "sender_id": 1,
        "sender_name": "Mik",
        "is_outgoing": True,
        "sent_at": datetime.now(UTC),
        "transcribed_at": None,
        **media_values,
    }


@pytest.mark.parametrize("media_first", [True, False])
def test_sync_batch_preserves_media_columns_in_any_message_order(media_first):
    media_info = MediaInfo(
        media_type="voice",
        file_name="voice.ogg",
        mime_type="audio/ogg",
        file_size=123,
        duration_seconds=5,
    )
    with patch(
        "app.services.sync_service.get_media_info",
        side_effect=[media_info, None],
    ):
        media_values = _media_values(SimpleNamespace(media=object()))
        text_values = _media_values(SimpleNamespace(media=None))

    rows = [
        _message_row(1, media_values),
        _message_row(2, text_values),
    ]
    if not media_first:
        rows.reverse()

    stmt = (
        pg_insert(TelegramMessage)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_telegram_messages_chat_msg")
        .returning(TelegramMessage.id)
    )
    compiled = str(stmt.compile(dialect=postgresql.dialect()))

    assert "media_file_name_m0" in compiled
    assert "media_file_name_m1" in compiled


async def test_telegram_media_download_has_an_operation_timeout(tmp_path):
    job = ClaimedMediaMessage(
        id=uuid4(),
        user_id=uuid4(),
        chat_id=uuid4(),
        telegram_message_id=123,
        caption=None,
        media_type="photo",
        file_name="photo.jpg",
        mime_type="image/jpeg",
        file_size=None,
        duration_seconds=None,
        existing_content_text=None,
        transcribed_at=None,
    )
    db = AsyncMock()
    db_result = MagicMock()
    db_result.scalar_one_or_none.return_value = object()
    db.execute.return_value = db_result

    @asynccontextmanager
    async def test_db_context():
        yield db

    client = AsyncMock()
    telegram_message = object()
    client.get_messages.return_value = telegram_message

    async def never_finishes(*_args, **_kwargs):
        await asyncio.Event().wait()

    client.download_media.side_effect = never_finishes
    media_info = MediaInfo(
        media_type="photo",
        file_name="photo.jpg",
        mime_type="image/jpeg",
        file_size=None,
        duration_seconds=None,
    )

    with (
        patch(
            "app.services.media_processing_service.get_db_context",
            side_effect=test_db_context,
        ),
        patch(
            "app.services.media_processing_service.get_client",
            new_callable=AsyncMock,
            return_value=client,
        ),
        patch(
            "app.services.media_processing_service._resolve_chat_entity",
            new_callable=AsyncMock,
            return_value=object(),
        ),
        patch(
            "app.services.media_processing_service.get_media_info",
            return_value=media_info,
        ),
        patch("app.services.media_processing_service.settings") as service_settings,
    ):
        service_settings.media_download_timeout_seconds = 0.01
        with pytest.raises(MediaDownloadError, match="timed out after 0.01 seconds"):
            await asyncio.wait_for(
                _download_telegram_media(job, tmp_path),
                timeout=0.2,
            )

    client.disconnect.assert_awaited_once()


async def test_media_worker_reuses_client_and_disconnects_it_on_shutdown():
    await disconnect_media_clients()
    user_id = uuid4()
    db = AsyncMock()
    client = MagicMock()
    client.is_connected.return_value = True
    client.disconnect = AsyncMock()

    with patch(
        "app.services.media_processing_service.get_client",
        new_callable=AsyncMock,
        return_value=client,
    ) as create_client:
        first = await _get_media_client(user_id, db)
        second = await _get_media_client(user_id, db)

    assert first is client
    assert second is client
    create_client.assert_awaited_once_with(user_id, db)

    await disconnect_media_clients()
    client.disconnect.assert_awaited_once()


def test_realtime_listener_uses_the_bounded_priority_dispatcher():
    source = inspect.getsource(TelegramListener._handle_message)

    assert "enqueue_media_processing" not in source
