import asyncio
import logging
import random
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.tl.types import (
    Channel,
    Chat,
    Message,
    MessageMediaDocument,
    MessageMediaPhoto,
)
from telethon.tl.types import (
    User as TelegramUser,
)

from app.core.config import get_settings
from app.models.chat import ChatType, TelegramChat
from app.models.message import TelegramMessage
from app.models.sync_job import SyncJob, SyncStatus
from app.services.embedding_service import embed_messages
from app.services.rate_limiter import record_request
from app.services.telegram_client import get_client
from app.services.transcription_service import (
    TRANSCRIBABLE_MEDIA_TYPES,
    download_and_transcribe,
)

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
    try:
        record_request()  # Track iter_dialogs API call

        async for dialog in client.iter_dialogs(limit=settings.sync_dialog_limit):
            # Extract last message preview
            last_msg_text = None
            last_msg_sender = None
            if dialog.message:
                msg = dialog.message
                if msg.message:
                    last_msg_text = msg.message[:200]
                elif msg.media:
                    media_label = _get_media_type(msg)
                    last_msg_text = f"[{media_label}]" if media_label else "[media]"
                last_msg_sender = _get_sender_name(msg)

            values = {
                "user_id": user_id,
                "telegram_chat_id": dialog.entity.id,
                "chat_type": _get_chat_type(dialog),
                "title": _get_chat_title(dialog),
                "username": getattr(dialog.entity, "username", None),
                "last_activity_at": dialog.date,
                "last_message_text": last_msg_text,
                "last_message_sender_name": last_msg_sender,
                "unread_count": dialog.unread_count,
            }
            stmt = pg_insert(TelegramChat).values(**values)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_telegram_chats_user_chat",
                set_={
                    "title": stmt.excluded.title,
                    "username": stmt.excluded.username,
                    "last_activity_at": stmt.excluded.last_activity_at,
                    # Telegram dialog payloads sometimes omit preview fields.
                    # Keep existing preview when the incoming value is null.
                    "last_message_text": func.coalesce(
                        stmt.excluded.last_message_text,
                        TelegramChat.last_message_text,
                    ),
                    "last_message_sender_name": func.coalesce(
                        stmt.excluded.last_message_sender_name,
                        TelegramChat.last_message_sender_name,
                    ),
                    "unread_count": func.coalesce(
                        stmt.excluded.unread_count,
                        TelegramChat.unread_count,
                        0,
                    ),
                },
            ).returning(TelegramChat)
            result = await db.execute(stmt)
            chat = result.scalar_one()
            chats.append(chat)

        await db.flush()
    finally:
        await client.disconnect()
    return chats


async def sync_messages(
    db: AsyncSession,
    user_id: UUID,
    chat_id: UUID,
    job_id: UUID,
    limit: int | None = None,
    on_progress: Callable[[int], None] | None = None,
    client: "TelegramClient | None" = None,
) -> int:
    """Sync messages for a specific chat. Returns count of messages synced.

    If client is provided (e.g. from the listener service), it is used directly
    instead of calling get_client().
    """

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

    owns_client = False
    if client is None:
        client = await get_client(user_id, db)
        owns_client = True
    messages_synced = 0
    batch_values = []
    batch_count = 0
    last_id = chat.last_message_id
    inserted_message_ids: list[UUID] = []

    messages_seen = 0

    # Pre-load telegram_message_ids that already have transcription in this chat.
    # This avoids expensive re-download + re-transcribe for already-transcribed msgs.
    already_transcribed: set[int] = set()
    _rows = (
        await db.execute(
            select(TelegramMessage.telegram_message_id).where(
                TelegramMessage.chat_id == chat_id,
                TelegramMessage.transcribed_at.isnot(None),
            )
        )
    ).scalars().all()
    already_transcribed = set(_rows)

    # Always fetch newest-first with the requested limit.
    # When limit is None ("Sync All"): Telethon fetches entire chat history.
    # When limit is N ("Sync Latest N"): Telethon fetches the N newest messages.
    # Deduplication is handled by the DB constraint + on_conflict_do_update:
    #   - Truly new messages are inserted normally.
    #   - Existing messages are updated ONLY when the incoming row carries a
    #     transcription and the stored row does not (backfills voice/video_note
    #     transcriptions added after the initial sync).
    #   - All other duplicates are silently skipped (WHERE prevents a no-op UPDATE).
    iter_kwargs = {"limit": limit, "wait_time": 0.5}

    try:
        async for message in client.iter_messages(chat.telegram_chat_id, **iter_kwargs):
            messages_seen += 1

            if not message.text and not message.media:
                continue

            media_type = _get_media_type(message)
            msg_values = {
                "chat_id": chat_id,
                "telegram_message_id": message.id,
                "text": message.text,
                "has_media": bool(message.media),
                "media_type": media_type,
                "sender_id": message.sender_id,
                "sender_name": _get_sender_name(message),
                "is_outgoing": message.out,
                "sent_at": message.date,
                "transcribed_at": None,
            }

            # Transcribe voice/video_note messages (skip if already transcribed in DB)
            if (
                media_type in TRANSCRIBABLE_MEDIA_TYPES
                and message.id not in already_transcribed
            ):
                try:
                    transcript = await download_and_transcribe(client, message)
                    if transcript:
                        msg_values["text"] = transcript
                        msg_values["transcribed_at"] = datetime.now(UTC)
                        already_transcribed.add(message.id)
                except Exception as e:
                    logger.warning(
                        f"Transcription failed for message {message.id}: {e}"
                    )
                # Keep heartbeat alive during voice-heavy batches
                if on_progress:
                    on_progress(messages_seen)

            batch_values.append(msg_values)
            messages_synced += 1

            # Update last_id
            if not last_id or message.id > last_id:
                last_id = message.id

            # Batch upsert: insert new messages, backfill transcriptions on conflict
            if len(batch_values) >= settings.sync_batch_size:
                stmt = pg_insert(TelegramMessage).values(batch_values)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_telegram_messages_chat_msg",
                    set_={
                        "text": stmt.excluded.text,
                        "transcribed_at": stmt.excluded.transcribed_at,
                    },
                    where=(
                        stmt.excluded.transcribed_at.isnot(None)
                        & TelegramMessage.transcribed_at.is_(None)
                    ),
                ).returning(TelegramMessage.id)
                result = await db.execute(stmt)
                inserted_ids = [row[0] for row in result.fetchall()]
                inserted_message_ids.extend(inserted_ids)
                skipped = len(batch_values) - len(inserted_ids)
                messages_synced -= skipped

                batch_values = []
                batch_count += 1
                record_request()  # Track batch API call

                if on_progress:
                    on_progress(messages_seen)

                # Commit batch so progress is visible and work survives interruptions
                job.messages_processed = messages_synced
                job.last_processed_id = last_id
                await db.commit()

                # Progressive jittered delay — increases every N batches
                progressive_extra = (
                    batch_count // settings.sync_progressive_delay_interval
                ) * settings.sync_progressive_delay_step
                base_delay = settings.sync_delay_seconds + progressive_extra
                await _jittered_sleep(base_delay, settings.sync_delay_jitter)

        # Insert remaining batch
        if batch_values:
            stmt = pg_insert(TelegramMessage).values(batch_values)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_telegram_messages_chat_msg",
                set_={
                    "text": stmt.excluded.text,
                    "transcribed_at": stmt.excluded.transcribed_at,
                },
                where=(
                    stmt.excluded.transcribed_at.isnot(None)
                    & TelegramMessage.transcribed_at.is_(None)
                ),
            ).returning(TelegramMessage.id)
            result = await db.execute(stmt)
            inserted_ids = [row[0] for row in result.fetchall()]
            inserted_message_ids.extend(inserted_ids)
            skipped = len(batch_values) - len(inserted_ids)
            messages_synced -= skipped

        if on_progress:
            on_progress(messages_seen)

        # Best-effort embedding generation for newly inserted text messages.
        # Embedding failures should not fail message sync.
        if inserted_message_ids:
            try:
                await embed_messages(db, inserted_message_ids)
            except Exception as e:
                logger.exception(
                    f"Embedding step failed after sync for chat {chat_id}: {e}"
                )

        # Update chat and job
        chat.last_message_id = last_id
        chat.last_sync_at = datetime.now(UTC)
        chat.total_messages_synced = (
            await db.execute(
                select(func.count()).where(TelegramMessage.chat_id == chat_id)
            )
        ).scalar()

        # Update chat preview from latest DB message
        latest_msg = (
            await db.execute(
                select(TelegramMessage)
                .where(TelegramMessage.chat_id == chat_id)
                .order_by(
                    TelegramMessage.sent_at.desc(),
                    TelegramMessage.telegram_message_id.desc(),
                    TelegramMessage.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_msg:
            preview = latest_msg.text[:200] if latest_msg.text else None
            if not preview and latest_msg.media_type:
                preview = f"[{latest_msg.media_type}]"
            chat.last_message_text = preview
            chat.last_message_sender_name = latest_msg.sender_name
            chat.last_activity_at = latest_msg.sent_at

        job.messages_processed = messages_synced
        job.last_processed_id = last_id
        await db.commit()

        return messages_synced
    finally:
        if owns_client:
            await client.disconnect()


async def create_sync_job(
    db: AsyncSession, user_id: UUID, chat_id: UUID | None = None
) -> SyncJob:
    """Create a new sync job."""
    job = SyncJob(user_id=user_id, chat_id=chat_id, status=SyncStatus.PENDING)
    db.add(job)
    await db.flush()
    return job
