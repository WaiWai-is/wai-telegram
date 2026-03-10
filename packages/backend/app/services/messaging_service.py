import ipaddress
import logging
import socket
import tempfile
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import (
    ChatWriteForbiddenError,
    FloodWaitError,
    RPCError,
    UserBannedInChannelError,
)

from app.models.chat import TelegramChat
from app.services.telegram_client import get_client

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def _validate_url(url: str) -> None:
    """Validate URL to prevent SSRF attacks."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must have a hostname")

    # Resolve hostname and check for private IPs
    try:
        results = socket.getaddrinfo(
            hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
    except socket.gaierror as e:
        raise ValueError(f"Cannot resolve hostname: {hostname}") from e

    for _family, _type, _proto, _canonname, sockaddr in results:
        # Strip IPv6 zone ID (e.g. "fe80::1%eth0" → "fe80::1")
        addr = sockaddr[0].split("%")[0]
        ip = ipaddress.ip_address(addr)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError(
                "URLs pointing to private/internal networks are not allowed"
            )


def _sanitize_file_name(name: str) -> str:
    """Sanitize file name to remove dangerous characters."""
    # Take only the last path component
    name = Path(name).name
    # Remove dangerous characters
    for ch in "\x00/\\|<>:\"'":
        name = name.replace(ch, "_")
    # Remove leading dashes/dots (prevent command option injection / hidden files)
    name = name.lstrip("-.")
    # Limit length
    if len(name) > 200:
        suffix = Path(name).suffix[:20]
        name = name[: 200 - len(suffix)] + suffix
    return name or "file"


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


def _handle_telethon_error(e: Exception) -> NoReturn:
    """Convert Telethon exceptions to user-friendly ValueErrors."""
    if isinstance(e, FloodWaitError):
        raise ValueError(f"Telegram rate limit: please wait {e.seconds} seconds") from e
    if isinstance(e, ChatWriteForbiddenError):
        raise ValueError("You don't have permission to write in this chat") from e
    if isinstance(e, UserBannedInChannelError):
        raise ValueError("You are banned from writing in this channel") from e
    raise ValueError(f"Telegram error: {e}") from e


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
    except (
        FloodWaitError,
        ChatWriteForbiddenError,
        UserBannedInChannelError,
        RPCError,
        ConnectionError,
        OSError,
    ) as e:
        _handle_telethon_error(e)
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
    _validate_url(file_url)
    telegram_chat_id = await _get_telegram_chat_id(db, user_id, chat_id)

    if not file_name:
        path = urlparse(file_url).path
        file_name = Path(path).name or "file"
    file_name = _sanitize_file_name(file_name)
    suffix = Path(file_name).suffix or ""

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        # Stream download directly to disk to avoid buffering large files in memory.
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
            async with http.stream("GET", file_url) as response:
                response.raise_for_status()

                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_FILE_SIZE:
                    raise ValueError(
                        f"File too large: {int(content_length)} bytes "
                        f"(max {MAX_FILE_SIZE // 1024 // 1024} MB)"
                    )

                total_size = 0
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    total_size += len(chunk)
                    if total_size > MAX_FILE_SIZE:
                        raise ValueError(
                            f"File exceeds maximum size of "
                            f"{MAX_FILE_SIZE // 1024 // 1024} MB"
                        )
                    tmp.write(chunk)
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
        except (
            FloodWaitError,
            ChatWriteForbiddenError,
            UserBannedInChannelError,
            RPCError,
            ConnectionError,
            OSError,
        ) as e:
            _handle_telethon_error(e)
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
    except (
        FloodWaitError,
        ChatWriteForbiddenError,
        UserBannedInChannelError,
        RPCError,
        ConnectionError,
        OSError,
    ) as e:
        _handle_telethon_error(e)
    finally:
        await client.disconnect()
