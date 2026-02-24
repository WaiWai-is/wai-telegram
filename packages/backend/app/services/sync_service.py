import asyncio
import logging
import random
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.tl.types import (
    Channel,
    Chat,
    User as TelegramUser,
    Message,
    MessageMediaDocument,
    MessageMediaPhoto,
)

from app.core.config import get_settings
from app.models.chat import ChatType, TelegramChat
from app.models.message import TelegramMessage
from app.models.sync_job import SyncJob, SyncStatus
from app.services.embedding_service import embed_messages
from app.services.rate_limiter import record_request
from app.services.telegram_client import get_client

logger = logging.getLogger(__name__)
settings = get_settings()


def _get_chat_type(dialog) -> ChatType:
    """Determine chat type from Telethon dialog entity."""
    entity = dialog.entity
    if isinstance(entity, TelegramUser):
        return ChatType.PRIVATE
    elif isinstance(entity, Chat):
        return ChatType.GROUP
    elif isinstance(entity, Channel):
        if entity.megagroup:
            return ChatType.SUPERGROUP
        return ChatType.CHANNEL
    return ChatType.GROUP


def _get_chat_title(dialog) -> str:
    """Get chat title from dialog entity."""
    entity = dialog.entity
    if isinstance(entity, TelegramUser):
        parts = [entity.first_name or "", entity.last_name or ""]
        return " ".join(p for p in parts if p) or "Unknown"
    return getattr(entity, "title", "Unknown")


def _get_sender_name(message: Message) -> str | None:
    """Extract sender name from message."""
    if not message.sender:
        return None
    sender = message.sender
    if isinstance(sender, TelegramUser):
        parts = [sender.first_name or "", sender.last_name or ""]
        return " ".join(p for p in parts if p) or None
    return getattr(sender, "title", None)


def _get_media_type(message: Message) -> str | None:
    """Get media type from message."""
    if not message.media:
        return None
    if isinstance(message.media, MessageMediaPhoto):
        return "photo"
    if isinstance(message.media, MessageMediaDocument):
        doc = message.media.document
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


async def _jittered_sleep(base: float, jitter: float) -> None:
    """Sleep for base +/- jitter seconds."""
    delay = base + random.uniform(-jitter, jitter)
    await asyncio.sleep(max(0.1, delay))


async def sync_chats(db: AsyncSession, user_id: UUID) -> list[TelegramChat]:
    """Sync user's chat list from Telegram using upsert for atomicity."""
    client = await get_client(user_id, db)
    chats = []
    record_request()  # Track iter_dialogs API call

    async for dialog in client.iter_dialogs(limit=settings.sync_dialog_limit):
        values = {
            "user_id": user_id,
            "telegram_chat_id": dialog.entity.id,
            "chat_type": _get_chat_type(dialog),
            "title": _get_chat_title(dialog),
            "username": getattr(dialog.entity, "username", None),
        }
        stmt = pg_insert(TelegramChat).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_telegram_chats_user_chat",
            set_={"title": stmt.excluded.title, "username": stmt.excluded.username},
        ).returning(TelegramChat)
        result = await db.execute(stmt)
        chat = result.scalar_one()
        chats.append(chat)

    await db.flush()
    return chats


async def sync_messages(
    db: AsyncSession,
    user_id: UUID,
    chat_id: UUID,
    job_id: UUID,
    limit: int | None = None,
) -> int:
    """Sync messages for a specific chat. Returns count of messages synced."""
    # Get chat
    result = await db.execute(
        select(TelegramChat).where(
            TelegramChat.id == chat_id, TelegramChat.user_id == user_id
        )
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise ValueError("Chat not found")

    # Get job
    result = await db.execute(select(SyncJob).where(SyncJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError("Sync job not found")

    client = await get_client(user_id, db)
    messages_synced = 0
    batch_values = []
    batch_count = 0
    last_id = chat.last_message_id
    inserted_message_ids: list[UUID] = []

    async for message in client.iter_messages(
        chat.telegram_chat_id,
        min_id=last_id or 0,
        reverse=True,
        limit=limit,
        wait_time=0.5,
    ):
        if not message.text and not message.media:
            continue

        batch_values.append({
            "chat_id": chat_id,
            "telegram_message_id": message.id,
            "text": message.text,
            "has_media": bool(message.media),
            "media_type": _get_media_type(message),
            "sender_id": message.sender_id,
            "sender_name": _get_sender_name(message),
            "is_outgoing": message.out,
            "sent_at": message.date,
        })
        messages_synced += 1

        # Update last_id
        if not last_id or message.id > last_id:
            last_id = message.id

        # Batch upsert using on_conflict_do_nothing for idempotency
        if len(batch_values) >= settings.sync_batch_size:
            stmt = pg_insert(TelegramMessage).values(batch_values)
            stmt = stmt.on_conflict_do_nothing(
                constraint="uq_telegram_messages_chat_msg"
            ).returning(TelegramMessage.id)
            result = await db.execute(stmt)
            inserted_ids = [row[0] for row in result.fetchall()]
            inserted_message_ids.extend(inserted_ids)
            skipped = len(batch_values) - len(inserted_ids)
            messages_synced -= skipped

            batch_values = []
            batch_count += 1
            record_request()  # Track batch API call

            # Update job progress
            job.messages_processed = messages_synced
            job.last_processed_id = last_id
            await db.flush()

            # Progressive jittered delay — increases every N batches
            progressive_extra = (
                (batch_count // settings.sync_progressive_delay_interval)
                * settings.sync_progressive_delay_step
            )
            base_delay = settings.sync_delay_seconds + progressive_extra
            await _jittered_sleep(base_delay, settings.sync_delay_jitter)

    # Insert remaining batch
    if batch_values:
        stmt = pg_insert(TelegramMessage).values(batch_values)
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_telegram_messages_chat_msg"
        ).returning(TelegramMessage.id)
        result = await db.execute(stmt)
        inserted_ids = [row[0] for row in result.fetchall()]
        inserted_message_ids.extend(inserted_ids)
        skipped = len(batch_values) - len(inserted_ids)
        messages_synced -= skipped

    # Best-effort embedding generation for newly inserted text messages.
    # Embedding failures should not fail message sync.
    if inserted_message_ids:
        try:
            await embed_messages(db, inserted_message_ids)
        except Exception as e:
            logger.exception(f"Embedding step failed after sync for chat {chat_id}: {e}")

    # Update chat and job
    chat.last_message_id = last_id
    chat.last_sync_at = datetime.now(UTC)
    chat.total_messages_synced = (
        await db.execute(
            select(func.count()).where(TelegramMessage.chat_id == chat_id)
        )
    ).scalar()

    job.messages_processed = messages_synced
    job.last_processed_id = last_id
    await db.flush()

    return messages_synced


async def create_sync_job(
    db: AsyncSession, user_id: UUID, chat_id: UUID | None = None
) -> SyncJob:
    """Create a new sync job."""
    job = SyncJob(user_id=user_id, chat_id=chat_id, status=SyncStatus.PENDING)
    db.add(job)
    await db.flush()
    return job
