import asyncio
import json
import logging
from datetime import UTC, datetime
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.types import (
    Channel,
    Chat as TelegramGroupChat,
    MessageMediaDocument,
    MessageMediaPhoto,
    User as TelegramUser,
)

from app.core.config import get_settings
from app.core.database import get_db_context
from app.core.security import decrypt_session
from app.models.chat import ChatType, TelegramChat
from app.models.message import TelegramMessage
from app.models.session import TelegramSession
from app.models.settings import UserSettings
from app.models.sync_job import SyncJob, SyncStatus
from app.services.embedding_service import embed_messages
from app.services.sync_service import sync_messages

logger = logging.getLogger(__name__)
settings = get_settings()

HEARTBEAT_INTERVAL = 30
ACTIVE_KEY_TTL = 60
HEALTH_CHECK_INTERVAL = 300  # 5 minutes


def _get_media_type(media) -> str | None:
    """Get media type from message media."""
    if not media:
        return None
    if isinstance(media, MessageMediaPhoto):
        return "photo"
    if isinstance(media, MessageMediaDocument):
        doc = media.document
        if doc:
            for attr in doc.attributes:
                if hasattr(attr, "voice") and attr.voice:
                    return "voice"
                if hasattr(attr, "round_message") and attr.round_message:
                    return "video_note"
                if hasattr(attr, "file_name"):
                    return "document"
            mime = getattr(doc, "mime_type", "")
            if mime.startswith("video/"):
                return "video"
            if mime.startswith("audio/"):
                return "audio"
        return "document"
    return "other"


def _get_sender_name(sender) -> str | None:
    """Extract sender name from sender entity."""
    if not sender:
        return None
    if isinstance(sender, TelegramUser):
        parts = [sender.first_name or "", sender.last_name or ""]
        return " ".join(p for p in parts if p) or None
    return getattr(sender, "title", None)


class TelegramListener:
    def __init__(self):
        self.clients: dict[UUID, TelegramClient] = {}
        self.redis: aioredis.Redis | None = None

    async def run(self):
        """Main entry point."""
        self.redis = aioredis.from_url(settings.redis_url)
        logger.info("Listener starting — loading enabled users")
        await self._load_enabled_users()
        logger.info(f"Listener running with {len(self.clients)} active client(s)")
        await asyncio.gather(
            self._redis_command_loop(),
            self._heartbeat_loop(),
            self._health_check_loop(),
        )

    async def _load_enabled_users(self):
        """Connect Telethon clients for all users with realtime_sync_enabled."""
        async with get_db_context() as db:
            result = await db.execute(
                select(UserSettings).where(UserSettings.realtime_sync_enabled == True)
            )
            for user_settings in result.scalars().all():
                try:
                    await self._start_user(user_settings.user_id)
                except Exception as e:
                    logger.error(f"Failed to start listener for user {user_settings.user_id}: {e}")

    async def _start_user(self, user_id: UUID):
        """Create Telethon client with event handlers."""
        if user_id in self.clients:
            logger.info(f"Client already active for user {user_id}")
            return

        async with get_db_context() as db:
            result = await db.execute(
                select(TelegramSession).where(
                    TelegramSession.user_id == user_id,
                    TelegramSession.is_active == True,
                )
            )
            session = result.scalar_one_or_none()
            if not session:
                logger.warning(f"No active Telegram session for user {user_id}")
                return

            session_string = decrypt_session(session.session_string)

        client = TelegramClient(
            StringSession(session_string),
            settings.telegram_api_id,
            settings.telegram_api_hash,
            device_model=settings.telegram_device_model,
            system_version=settings.telegram_system_version,
            app_version=settings.telegram_app_version,
            flood_sleep_threshold=settings.telegram_flood_sleep_threshold,
            receive_updates=True,
        )
        await client.connect()

        if not await client.is_user_authorized():
            logger.error(f"Telethon session not authorized for user {user_id}")
            await client.disconnect()
            return

        @client.on(events.NewMessage)
        async def on_message(event):
            await self._handle_message(user_id, event)

        # Start receiving updates
        await client.catch_up()

        self.clients[user_id] = client
        await self.redis.set(f"listener:active:{user_id}", "1", ex=ACTIVE_KEY_TTL)
        logger.info(f"Listener started for user {user_id}")

    async def _stop_user(self, user_id: UUID):
        """Disconnect a user's Telethon client."""
        client = self.clients.pop(user_id, None)
        if client:
            await client.disconnect()
        await self.redis.delete(f"listener:active:{user_id}")
        logger.info(f"Listener stopped for user {user_id}")

    async def _auto_create_chat(self, db, user_id: UUID, entity, chat_id_tg: int) -> TelegramChat | None:
        """Auto-create a TelegramChat record from a Telethon entity."""
        if isinstance(entity, TelegramUser):
            chat_type = ChatType.PRIVATE
            title = _get_sender_name(entity) or f"User {chat_id_tg}"
            username = entity.username
        elif isinstance(entity, Channel):
            chat_type = ChatType.SUPERGROUP if entity.megagroup else ChatType.CHANNEL
            title = entity.title or f"Channel {chat_id_tg}"
            username = entity.username
        elif isinstance(entity, TelegramGroupChat):
            chat_type = ChatType.GROUP
            title = entity.title or f"Group {chat_id_tg}"
            username = None
        else:
            logger.warning(f"Unknown entity type for chat {chat_id_tg}: {type(entity)}")
            return None

        stmt = pg_insert(TelegramChat).values(
            user_id=user_id,
            telegram_chat_id=chat_id_tg,
            chat_type=chat_type,
            title=title,
            username=username,
        )
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_telegram_chats_user_chat"
        ).returning(TelegramChat.id)
        result = await db.execute(stmt)
        row = result.fetchone()
        if row:
            await db.flush()
            # Re-fetch the full object
            result = await db.execute(
                select(TelegramChat).where(TelegramChat.id == row[0])
            )
            chat = result.scalar_one()
            logger.info(f"Auto-created chat '{title}' ({chat_id_tg}) for user {user_id}")
            return chat

        # on_conflict_do_nothing means it already exists — fetch it
        result = await db.execute(
            select(TelegramChat).where(
                TelegramChat.user_id == user_id,
                TelegramChat.telegram_chat_id == chat_id_tg,
            )
        )
        return result.scalar_one_or_none()

    async def _handle_message(self, user_id: UUID, event):
        """Save incoming message to DB."""
        message = event.message
        if not message.text and not message.media:
            return

        try:
            chat_id_tg = event.chat_id
            inserted_id = None

            async with get_db_context() as db:
                # Find our chat record by telegram_chat_id
                result = await db.execute(
                    select(TelegramChat).where(
                        TelegramChat.user_id == user_id,
                        TelegramChat.telegram_chat_id == chat_id_tg,
                    )
                )
                chat = result.scalar_one_or_none()
                if not chat:
                    try:
                        entity = await event.get_chat()
                        chat = await self._auto_create_chat(db, user_id, entity, chat_id_tg)
                        if not chat:
                            return
                    except Exception as e:
                        logger.warning(f"Could not auto-create chat {chat_id_tg}: {e}")
                        return

                try:
                    sender = await event.get_sender()
                except FloodWaitError as e:
                    logger.warning(f"FloodWait in listener for user {user_id}: {e.seconds}s")
                    await asyncio.sleep(e.seconds)
                    sender = await event.get_sender()

                values = {
                    "chat_id": chat.id,
                    "telegram_message_id": message.id,
                    "text": message.text,
                    "has_media": bool(message.media),
                    "media_type": _get_media_type(message.media),
                    "sender_id": message.sender_id,
                    "sender_name": _get_sender_name(sender),
                    "is_outgoing": message.out,
                    "sent_at": message.date,
                }
                stmt = pg_insert(TelegramMessage).values(**values)
                stmt = stmt.on_conflict_do_nothing(
                    constraint="uq_telegram_messages_chat_msg"
                ).returning(TelegramMessage.id)
                result = await db.execute(stmt)
                inserted = result.fetchone()
                if inserted:
                    inserted_id = inserted[0]

                # Update chat's last_message_id
                if not chat.last_message_id or message.id > chat.last_message_id:
                    chat.last_message_id = message.id
                chat.last_sync_at = datetime.now(UTC)
                chat.total_messages_synced = (
                    await db.execute(
                        select(func.count()).where(TelegramMessage.chat_id == chat.id)
                    )
                ).scalar()

            # Best-effort embed in separate session
            if inserted_id:
                try:
                    async with get_db_context() as db:
                        await embed_messages(db, [inserted_id])
                except Exception as e:
                    logger.debug(f"Embedding failed for real-time message: {e}")

        except Exception as e:
            logger.error(f"Error handling real-time message for user {user_id}: {e}")

    async def _handle_sync(self, cmd: dict):
        """Perform manual sync using existing sync_messages() function."""
        user_id = UUID(cmd["user_id"])
        chat_id = UUID(cmd["chat_id"])
        job_id = UUID(cmd["job_id"])
        limit = cmd.get("limit")

        client = self.clients.get(user_id)
        if not client:
            logger.error(f"No active client for user {user_id} during sync command")
            return

        try:
            async with get_db_context() as db:
                result = await db.execute(select(SyncJob).where(SyncJob.id == job_id))
                job = result.scalar_one_or_none()
                if not job:
                    logger.error(f"Sync job {job_id} not found")
                    return
                job.status = SyncStatus.IN_PROGRESS
                job.error_message = None
                job.completed_at = None
                await db.commit()

                count = await sync_messages(db, user_id, chat_id, job_id, limit, client=client)

                job.status = SyncStatus.COMPLETED
                job.completed_at = datetime.now(UTC)
                job.messages_processed = count
                await db.commit()

                logger.info(f"Listener sync completed: chat {chat_id}, {count} messages")
        except Exception as e:
            logger.error(f"Listener sync failed for chat {chat_id}: {e}")
            async with get_db_context() as db:
                result = await db.execute(select(SyncJob).where(SyncJob.id == job_id))
                job = result.scalar_one_or_none()
                if job:
                    job.status = SyncStatus.FAILED
                    job.error_message = str(e)[:500]
                    await db.commit()

    async def _redis_command_loop(self):
        """Listen for commands from API."""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe("listener:cmd:global")

        # Also subscribe to per-user channels for active users
        for user_id in list(self.clients.keys()):
            await pubsub.subscribe(f"listener:cmd:{user_id}")

        async for msg in pubsub.listen():
            if msg["type"] != "message":
                continue
            try:
                cmd = json.loads(msg["data"])
                match cmd.get("command"):
                    case "start_user":
                        uid = UUID(cmd["user_id"])
                        await self._start_user(uid)
                        await pubsub.subscribe(f"listener:cmd:{uid}")
                    case "stop_user":
                        uid = UUID(cmd["user_id"])
                        await pubsub.unsubscribe(f"listener:cmd:{uid}")
                        await self._stop_user(uid)
                    case "sync_chat":
                        await self._handle_sync(cmd)
                    case _:
                        logger.warning(f"Unknown listener command: {cmd}")
            except Exception as e:
                logger.error(f"Error processing listener command: {e}")

    async def _heartbeat_loop(self):
        """Refresh Redis active keys every 30s, only for connected clients."""
        while True:
            for user_id, client in list(self.clients.items()):
                if client.is_connected():
                    await self.redis.set(
                        f"listener:active:{user_id}", "1", ex=ACTIVE_KEY_TTL
                    )
                else:
                    logger.warning(f"Client disconnected for user {user_id}")
                    await self.redis.delete(f"listener:active:{user_id}")
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def _health_check_loop(self):
        """Periodically verify client health and catch up missed updates."""
        while True:
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)
            for user_id, client in list(self.clients.items()):
                try:
                    if client.is_connected():
                        await client.catch_up()
                        logger.debug(f"Health check catch_up completed for user {user_id}")
                except Exception as e:
                    logger.error(f"Health check failed for user {user_id}: {e}")
