import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import FloodWaitError
from telethon.tl.types import (
    Channel,
    Chat,
    User as TelegramUser,
    Message,
    MessageMediaDocument,
    MessageMediaPhoto,
)

from app.core.config import get_settings
from app.core.database import get_db_context
from app.models.chat import ChatType, TelegramChat
from app.models.message import TelegramMessage
from app.models.sync_job import SyncJob, SyncStatus
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


async def sync_chats(db: AsyncSession, user_id: UUID) -> list[TelegramChat]:
    """Sync user's chat list from Telegram."""
    client = await get_client(user_id, db)
    chats = []

    async for dialog in client.iter_dialogs():
        # Check if chat exists
        result = await db.execute(
            select(TelegramChat).where(
                TelegramChat.user_id == user_id,
                TelegramChat.telegram_chat_id == dialog.entity.id,
            )
        )
        chat = result.scalar_one_or_none()

        if chat:
            # Update existing
            chat.title = _get_chat_title(dialog)
            chat.username = getattr(dialog.entity, "username", None)
        else:
            # Create new
            chat = TelegramChat(
                user_id=user_id,
                telegram_chat_id=dialog.entity.id,
                chat_type=_get_chat_type(dialog),
                title=_get_chat_title(dialog),
                username=getattr(dialog.entity, "username", None),
            )
            db.add(chat)

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
    batch = []
    last_id = chat.last_message_id

    try:
        # Use offset_id for inclusive range (min_id is exclusive and can skip messages)
        # offset_id=X returns messages with id < X, so we subtract 1 to include last_id
        offset = (last_id - 1) if last_id else 0

        async for message in client.iter_messages(
            chat.telegram_chat_id,
            offset_id=offset,
            limit=limit,
        ):
            if not message.text and not message.media:
                continue

            # Skip if message already synced (using last_message_id as optimization)
            if last_id and message.id <= last_id:
                continue

            msg = TelegramMessage(
                chat_id=chat_id,
                telegram_message_id=message.id,
                text=message.text,
                has_media=bool(message.media),
                media_type=_get_media_type(message),
                sender_id=message.sender_id,
                sender_name=_get_sender_name(message),
                is_outgoing=message.out,
                sent_at=message.date,
            )
            batch.append(msg)
            messages_synced += 1

            # Update last_id
            if not last_id or message.id > last_id:
                last_id = message.id

            # Batch insert with IntegrityError handling for race conditions
            if len(batch) >= settings.sync_batch_size:
                try:
                    db.add_all(batch)
                    await db.flush()
                except IntegrityError as e:
                    # Handle race condition: message was inserted by another process
                    await db.rollback()
                    logger.warning(f"IntegrityError during batch insert, inserting one by one: {e}")
                    for msg in batch:
                        try:
                            db.add(msg)
                            await db.flush()
                        except IntegrityError:
                            await db.rollback()
                            messages_synced -= 1  # Don't count duplicates
                            logger.debug(f"Skipping duplicate message {msg.telegram_message_id}")
                batch = []

                # Update job progress
                job.messages_processed = messages_synced
                job.last_processed_id = last_id
                await db.flush()

                # Rate limit
                await asyncio.sleep(settings.sync_delay_seconds)

    except FloodWaitError as e:
        wait_time = int(e.seconds * settings.flood_wait_multiplier)
        logger.warning(f"FloodWait during sync: {wait_time}s")
        job.status = SyncStatus.FAILED
        job.error_message = f"Rate limited. Retry after {wait_time} seconds."
        await db.flush()
        raise

    # Insert remaining batch with IntegrityError handling
    if batch:
        try:
            db.add_all(batch)
            await db.flush()
        except IntegrityError as e:
            await db.rollback()
            logger.warning(f"IntegrityError in final batch, inserting one by one: {e}")
            for msg in batch:
                try:
                    db.add(msg)
                    await db.flush()
                except IntegrityError:
                    await db.rollback()
                    messages_synced -= 1

    # Update chat and job
    chat.last_message_id = last_id
    chat.last_sync_at = datetime.now(UTC)
    chat.total_messages_synced = (
        await db.execute(
            select(func.count()).where(TelegramMessage.chat_id == chat_id)
        )
    ).scalar()

    job.messages_processed = messages_synced
    job.status = SyncStatus.COMPLETED
    job.completed_at = datetime.now(UTC)
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
