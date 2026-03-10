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
from telethon.tl.types import (
    Channel,
    Chat,
    InputPeerChannel,
    InputPeerChat,
    InputPeerUser,
    User as TelegramUser,
)
from telethon.utils import get_peer_id

from app.models.chat import ChatType, TelegramChat
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


async def _get_chat(db: AsyncSession, user_id: UUID, chat_id: UUID) -> TelegramChat:
    """Look up a Telegram chat by our internal UUID."""
    result = await db.execute(
        select(TelegramChat).where(
            TelegramChat.id == chat_id,
            TelegramChat.user_id == user_id,
        )
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise ValueError(f"Chat {chat_id} not found")
    return chat


def _entity_chat_type(entity: object) -> ChatType | None:
    if isinstance(entity, TelegramUser):
        return ChatType.PRIVATE
    if isinstance(entity, Chat):
        return ChatType.GROUP
    if isinstance(entity, Channel):
        return ChatType.SUPERGROUP if entity.megagroup else ChatType.CHANNEL
    return None


def _dialog_matches_chat(dialog: object, chat: TelegramChat) -> bool:
    entity = getattr(dialog, "entity", None)
    if entity is None:
        return False

    entity_ids = {
        getattr(entity, "id", None),
        get_peer_id(entity),
    }
    if chat.telegram_chat_id not in entity_ids:
        return False

    return _entity_chat_type(entity) == chat.chat_type


def _raw_chat_id(chat: TelegramChat) -> int:
    chat_id = chat.telegram_chat_id
    if chat.chat_type == ChatType.GROUP:
        return abs(chat_id)
    if chat.chat_type in (ChatType.SUPERGROUP, ChatType.CHANNEL) and chat_id < 0:
        return abs(chat_id) - 10**12
    return chat_id


def _stored_input_peer(chat: TelegramChat):
    raw_chat_id = _raw_chat_id(chat)
    if chat.chat_type == ChatType.GROUP:
        return InputPeerChat(raw_chat_id)
    if chat.access_hash is None:
        return None
    if chat.chat_type == ChatType.PRIVATE:
        return InputPeerUser(raw_chat_id, chat.access_hash)
    if chat.chat_type in (ChatType.SUPERGROUP, ChatType.CHANNEL):
        return InputPeerChannel(raw_chat_id, chat.access_hash)
    return None


async def _remember_access_hash(
    db: AsyncSession, chat: TelegramChat, entity: object | None
) -> None:
    access_hash = getattr(entity, "access_hash", None)
    if access_hash is not None and chat.access_hash != access_hash:
        chat.access_hash = access_hash
        await db.flush()


async def _resolve_chat_entity(
    client,
    db: AsyncSession,
    chat: TelegramChat,
):
    """Resolve a sendable Telethon entity for a stored chat.

    Prefer a stored InputPeer when we already know access_hash. Fall back to
    dialog warm-up for legacy rows that predate access_hash persistence.
    """
    stored_peer = _stored_input_peer(chat)
    if stored_peer is not None:
        return stored_peer

    try:
        entity = await client.get_input_entity(chat.telegram_chat_id)
        await _remember_access_hash(db, chat, entity)
        return entity
    except ValueError:
        pass

    normalized_username = (chat.username or "").strip().removeprefix("@")

    async for dialog in client.iter_dialogs():
        if _dialog_matches_chat(dialog, chat):
            entity = getattr(dialog, "entity", None)
            await _remember_access_hash(db, chat, entity)
            return getattr(dialog, "input_entity", entity)

        if normalized_username:
            entity = getattr(dialog, "entity", None)
            if (
                entity is not None
                and getattr(entity, "username", None) == normalized_username
            ):
                await _remember_access_hash(db, chat, entity)
                return getattr(dialog, "input_entity", entity)

    if normalized_username:
        try:
            entity = await client.get_input_entity(normalized_username)
            await _remember_access_hash(db, chat, entity)
            return entity
        except (RPCError, ValueError):
            pass

    hint = chat.title or normalized_username or str(chat.telegram_chat_id)
    raise ValueError(
        "Could not resolve Telegram entity for chat "
        f"'{hint}'. Re-sync chats or open the dialog in Telegram, then try again."
    )


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
    chat = await _get_chat(db, user_id, chat_id)
    client = await get_client(user_id, db)
    try:
        entity = await _resolve_chat_entity(client, db, chat)
        result = await client.send_message(entity, text)
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
    chat = await _get_chat(db, user_id, chat_id)

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
            entity = await _resolve_chat_entity(client, db, chat)
            result = await client.send_file(
                entity,
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
    chat = await _get_chat(db, user_id, chat_id)
    client = await get_client(user_id, db)
    try:
        entity = await _resolve_chat_entity(client, db, chat)
        result = await client.send_message(
            entity,
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
