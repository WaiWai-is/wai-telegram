"""Serve a Telegram original straight through, without keeping it on disk.

The media volume is a fraction of the archive it fronts, so anything staged has
to be dropped again within hours - and a link handed out before that is dead
afterwards. Telegram still holds the file, and the fetch path already reads it
in chunks, so those chunks can go to the caller instead of to the disk.

Nothing is stored, so nothing expires: a download works whenever Telegram still
has the original, and the volume only ever holds what text extraction is
actively working on.
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.chat import TelegramChat
from app.models.message import TelegramMessage
from app.models.user import User
from app.services.media_content_service import get_media_info
from app.services.messaging_service import _resolve_chat_entity
from app.services.telegram_client import get_client
from app.services.telegram_links import media_download_filename

logger = logging.getLogger(__name__)
settings = get_settings()


class MediaStreamUnavailable(RuntimeError):
    """Telegram no longer has the original, so no amount of retrying helps."""


@dataclass(frozen=True)
class StreamableMedia:
    file_name: str
    mime_type: str
    size_bytes: int | None


async def open_media_stream(
    db: AsyncSession,
    user_id: UUID,
    chat_id: UUID,
    telegram_message_id: int,
    *,
    offset: int = 0,
) -> tuple[StreamableMedia, AsyncIterator[bytes]]:
    """Resolve one message and hand back its bytes as they arrive from Telegram.

    Everything that needs the database happens here, before the iterator is
    returned: the caller is a streaming response, and its session is gone by the
    time the first chunk is pulled.
    """
    row = (
        await db.execute(
            select(TelegramMessage, TelegramChat)
            .join(TelegramChat, TelegramChat.id == TelegramMessage.chat_id)
            .join(User, User.id == TelegramChat.user_id)
            .where(
                TelegramMessage.chat_id == chat_id,
                TelegramMessage.telegram_message_id == telegram_message_id,
                TelegramChat.user_id == user_id,
                User.is_active.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        raise MediaStreamUnavailable("Message not found")
    message, chat = row
    if not message.has_media:
        raise MediaStreamUnavailable("Message has no media")

    client = await get_client(user_id, db)
    try:
        peer = await _resolve_chat_entity(client, db, chat)
        # Refetched every time on purpose: a Telegram file reference goes stale
        # within hours, so a stored one cannot be used to start a download.
        telegram_message = await client.get_messages(
            peer, ids=message.telegram_message_id
        )
        if telegram_message is None or not getattr(telegram_message, "media", None):
            raise MediaStreamUnavailable("Telegram source media was deleted")
        info = get_media_info(telegram_message)
        if info is None:
            raise MediaStreamUnavailable("Telegram source has no downloadable media")
    except MediaStreamUnavailable:
        await _disconnect(client)
        raise
    except Exception:
        await _disconnect(client)
        raise

    describe = StreamableMedia(
        file_name=media_download_filename(
            info.file_name or message.media_file_name, info.mime_type
        ),
        mime_type=info.mime_type
        or message.media_mime_type
        or "application/octet-stream",
        size_bytes=info.file_size or message.media_file_size,
    )
    return describe, _iterate(client, telegram_message, offset)


async def _iterate(
    client: Any, telegram_message: Any, offset: int
) -> AsyncIterator[bytes]:
    try:
        async for chunk in client.iter_download(
            telegram_message,
            offset=offset,
            request_size=settings.media_download_chunk_bytes,
            chunk_size=settings.media_download_chunk_bytes,
        ):
            if chunk:
                yield bytes(chunk)
    finally:
        # The response may be abandoned mid-file, so the connection is closed
        # here rather than after a completed download.
        await _disconnect(client)


async def _disconnect(client: Any) -> None:
    try:
        result = client.disconnect()
        if result is not None:
            await result
    except Exception:  # pragma: no cover - a failed teardown must not mask the error
        logger.warning("Could not disconnect the streaming Telegram client")
