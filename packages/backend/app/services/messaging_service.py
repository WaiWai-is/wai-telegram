import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import TelegramChat
from app.services.telegram_client import get_client

logger = logging.getLogger(__name__)


async def _get_telegram_chat_id(db: AsyncSession, user_id: UUID, chat_id: UUID) -> int:
    """Look up the Telegram numeric chat ID from our internal UUID."""
    result = await db.execute(
        select(TelegramChat).where(
            TelegramChat.id == chat_id,
            TelegramChat.user_id == user_id,
        )
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise ValueError(f"Chat {chat_id} not found")
    return chat.telegram_chat_id


async def send_message(
    db: AsyncSession,
    user_id: UUID,
    chat_id: UUID,
    text: str,
) -> dict:
    """Send a text message to a Telegram chat via user's Telethon client."""
    telegram_chat_id = await _get_telegram_chat_id(db, user_id, chat_id)
    client = await get_client(user_id, db)
    try:
        result = await client.send_message(telegram_chat_id, text)
        return {
            "telegram_message_id": result.id,
            "chat_id": str(chat_id),
            "text": text,
        }
    finally:
        await client.disconnect()


async def send_file(
    db: AsyncSession,
    user_id: UUID,
    chat_id: UUID,
    file_url: str,
    caption: str | None = None,
    file_name: str | None = None,
) -> dict:
    """Download a file from URL and send it to a Telegram chat."""
    telegram_chat_id = await _get_telegram_chat_id(db, user_id, chat_id)

    # Download file
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
        response = await http.get(file_url)
        response.raise_for_status()

    # Determine file name from URL if not provided
    if not file_name:
        path = urlparse(file_url).path
        file_name = Path(path).name or "file"

    # Write to temp file and send via Telethon
    suffix = Path(file_name).suffix or ""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(response.content)
        tmp.flush()

        client = await get_client(user_id, db)
        try:
            result = await client.send_file(
                telegram_chat_id,
                tmp.name,
                caption=caption,
                file_name=file_name,
            )
            return {
                "telegram_message_id": result.id,
                "chat_id": str(chat_id),
                "file_name": file_name,
            }
        finally:
            await client.disconnect()


async def reply_to_message(
    db: AsyncSession,
    user_id: UUID,
    chat_id: UUID,
    telegram_message_id: int,
    text: str,
) -> dict:
    """Reply to a specific message in a Telegram chat."""
    telegram_chat_id = await _get_telegram_chat_id(db, user_id, chat_id)
    client = await get_client(user_id, db)
    try:
        result = await client.send_message(
            telegram_chat_id,
            text,
            reply_to=telegram_message_id,
        )
        return {
            "telegram_message_id": result.id,
            "chat_id": str(chat_id),
            "text": text,
        }
    finally:
        await client.disconnect()
