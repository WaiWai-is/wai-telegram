from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import FloodWaitError, RPCError

from app.services.messaging_service import _get_chat, _resolve_chat_entity
from app.services.telegram_client import (
    SESSION_EXPIRED_MESSAGE,
    TelegramSessionUnauthorizedError,
    get_client,
    invalidate_client_authorization,
    is_session_authorization_error,
)
from app.services.telegram_links import media_download_filename


@dataclass(frozen=True)
class DownloadedMedia:
    path: Path
    file_name: str
    mime_type: str
    file_size: int


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


async def download_telegram_media(
    db: AsyncSession,
    user_id: UUID,
    chat_id: UUID,
    telegram_message_id: int,
    destination: Path,
    *,
    stored_file_name: str | None = None,
    stored_mime_type: str | None = None,
) -> DownloadedMedia:
    """Download one media message through the owner's Telegram session."""
    chat = await _get_chat(db, user_id, chat_id)
    client = await get_client(user_id, db)
    try:
        entity = await _resolve_chat_entity(client, db, chat)
        message = await client.get_messages(entity, ids=telegram_message_id)
        if message is None or not getattr(message, "media", None):
            raise ValueError("Telegram message has no downloadable media")

        downloaded = await client.download_media(message, file=str(destination))
        if not downloaded:
            raise ValueError("Telegram media download returned no file")
        downloaded_path = Path(downloaded)
        if not downloaded_path.is_file() or downloaded_path.stat().st_size == 0:
            raise ValueError("Telegram media download returned no file")

        telegram_file = getattr(message, "file", None)
        mime_type = (
            _optional_text(stored_mime_type)
            or _optional_text(getattr(telegram_file, "mime_type", None))
            or "application/octet-stream"
        )
        file_name = media_download_filename(
            _optional_text(stored_file_name)
            or _optional_text(getattr(telegram_file, "name", None))
            or _optional_text(getattr(telegram_file, "file_name", None)),
            mime_type,
        )
        return DownloadedMedia(
            path=downloaded_path,
            file_name=file_name,
            mime_type=mime_type,
            file_size=downloaded_path.stat().st_size,
        )
    except (
        FloodWaitError,
        RPCError,
        ConnectionError,
        OSError,
    ) as exc:
        if is_session_authorization_error(exc):
            await invalidate_client_authorization(client, user_id, exc)
            raise TelegramSessionUnauthorizedError(SESSION_EXPIRED_MESSAGE) from exc
        if isinstance(exc, FloodWaitError):
            raise ValueError(
                f"Telegram rate limit: please wait {exc.seconds} seconds"
            ) from exc
        raise ValueError(
            f"Telegram media download failed: {type(exc).__name__}"
        ) from exc
    finally:
        await client.disconnect()
