"""Checkpointed Telegram metadata reconciliation without media-byte downloads."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import get_db_context
from app.models.chat import TelegramChat
from app.models.metadata import MetadataReconciliationCheckpoint
from app.models.message import MessageRevision, TelegramMessage
from app.services.media_content_service import get_media_info
from app.services.messaging_service import _resolve_chat_entity
from app.services.single_user import is_user_active
from app.services.sync_service import _get_sender_name
from app.services.telegram_client import get_client
from app.services.telegram_metadata import extract_message_metadata


def _metadata_message_values(chat: TelegramChat, message) -> dict:
    info = get_media_info(message)
    metadata = extract_message_metadata(
        message,
        file_name=info.file_name if info else None,
    )
    return {
        "chat_id": chat.id,
        "telegram_message_id": message.id,
        "text": message.text,
        "has_media": bool(message.media),
        "media_type": info.media_type if info else None,
        "media_file_name": info.file_name if info else None,
        "media_mime_type": info.mime_type if info else None,
        "media_file_size": info.file_size if info else None,
        "media_duration_seconds": info.duration_seconds if info else None,
        "sender_id": message.sender_id,
        "sender_name": _get_sender_name(message),
        "is_outgoing": message.out,
        "sent_at": message.date,
        **metadata,
    }


async def _checkpoint_for_chat(
    user_id: UUID,
    chat_id: UUID,
) -> MetadataReconciliationCheckpoint:
    async with get_db_context() as db:
        checkpoint = (
            await db.execute(
                select(MetadataReconciliationCheckpoint).where(
                    MetadataReconciliationCheckpoint.user_id == user_id,
                    MetadataReconciliationCheckpoint.chat_id == chat_id,
                )
            )
        ).scalar_one_or_none()
        if checkpoint is None:
            checkpoint = MetadataReconciliationCheckpoint(
                user_id=user_id,
                chat_id=chat_id,
                status="pending",
            )
            db.add(checkpoint)
            await db.flush()
        return checkpoint


async def _mark_checkpoint_failed(checkpoint_id: UUID, error: Exception) -> None:
    async with get_db_context() as db:
        checkpoint = await db.get(MetadataReconciliationCheckpoint, checkpoint_id)
        if checkpoint is not None:
            checkpoint.status = "failed"
            checkpoint.error_detail = f"{type(error).__name__}: {error}"[:1000]


async def reconcile_owner_metadata(
    user_id: UUID,
    *,
    batch_size: int = 500,
    max_messages: int | None = None,
) -> dict[str, int]:
    """Refresh current Telegram metadata while preserving all processed content."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    async with get_db_context() as db:
        if not await is_user_active(db, user_id):
            raise RuntimeError("Metadata reconciliation requires the active owner")
        chats = list(
            (
                await db.execute(
                    select(TelegramChat)
                    .where(TelegramChat.user_id == user_id)
                    .order_by(TelegramChat.id)
                )
            ).scalars()
        )
        client = await get_client(user_id, db)

    processed_total = 0
    completed_chats = 0
    try:
        for chat in chats:
            if max_messages is not None and processed_total >= max_messages:
                break
            checkpoint = await _checkpoint_for_chat(user_id, chat.id)
            checkpoint_id = checkpoint.id
            try:
                async with get_db_context() as db:
                    if not await is_user_active(db, user_id):
                        raise RuntimeError("Active owner was deactivated")
                    checkpoint = await db.get(
                        MetadataReconciliationCheckpoint, checkpoint_id
                    )
                    checkpoint.status = "running"
                    checkpoint.started_at = checkpoint.started_at or datetime.now(UTC)
                    checkpoint.completed_at = None
                    checkpoint.error_detail = None
                    peer = await _resolve_chat_entity(client, db, chat)
                    start_id = checkpoint.last_telegram_message_id

                pending_values: list[dict] = []
                last_message_id = start_id
                limit_reached = False
                iterator = client.iter_messages(
                    peer,
                    min_id=start_id,
                    reverse=True,
                    wait_time=0.5,
                )
                async for message in iterator:
                    if (
                        max_messages is not None
                        and processed_total + len(pending_values) >= max_messages
                    ):
                        limit_reached = True
                        break
                    if (
                        not message.text
                        and not message.media
                        and not getattr(message, "action", None)
                    ):
                        last_message_id = max(last_message_id, message.id)
                        continue
                    pending_values.append(_metadata_message_values(chat, message))
                    last_message_id = max(last_message_id, message.id)
                    if len(pending_values) >= batch_size:
                        processed = await _save_metadata_batch(
                            user_id,
                            checkpoint_id,
                            pending_values,
                            last_message_id,
                        )
                        processed_total += processed
                        pending_values = []
                if pending_values:
                    processed_total += await _save_metadata_batch(
                        user_id,
                        checkpoint_id,
                        pending_values,
                        last_message_id,
                    )
                async with get_db_context() as db:
                    checkpoint = await db.get(
                        MetadataReconciliationCheckpoint, checkpoint_id
                    )
                    checkpoint.last_telegram_message_id = last_message_id
                    checkpoint.status = "paused" if limit_reached else "complete"
                    checkpoint.completed_at = (
                        None if limit_reached else datetime.now(UTC)
                    )
                if not limit_reached:
                    completed_chats += 1
                else:
                    break
            except Exception as error:
                await _mark_checkpoint_failed(checkpoint_id, error)
                raise
    finally:
        await client.disconnect()
    return {"processed_messages": processed_total, "completed_chats": completed_chats}


async def _save_metadata_batch(
    user_id: UUID,
    checkpoint_id: UUID,
    values: list[dict],
    last_message_id: int,
) -> int:
    async with get_db_context() as db:
        if not await is_user_active(db, user_id):
            raise RuntimeError("Active owner was deactivated")
        identities = [
            (value["chat_id"], value["telegram_message_id"]) for value in values
        ]
        existing_messages = list(
            (
                await db.execute(
                    select(TelegramMessage)
                    .where(
                        tuple_(
                            TelegramMessage.chat_id,
                            TelegramMessage.telegram_message_id,
                        ).in_(identities)
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        existing_by_identity = {
            (message.chat_id, message.telegram_message_id): message
            for message in existing_messages
        }
        revision_rows = (
            await db.execute(
                select(
                    MessageRevision.message_id,
                    func.coalesce(func.max(MessageRevision.revision), 0),
                )
                .where(
                    MessageRevision.message_id.in_(
                        [message.id for message in existing_messages]
                    )
                )
                .group_by(MessageRevision.message_id)
            )
        ).all()
        latest_revisions = {
            message_id: revision for message_id, revision in revision_rows
        }
        for value in values:
            current = existing_by_identity.get(
                (value["chat_id"], value["telegram_message_id"])
            )
            if current is None:
                continue
            if current.text == value["text"] and current.entities == value["entities"]:
                continue
            next_revision = latest_revisions.get(current.id, 0) + 1
            latest_revisions[current.id] = next_revision
            db.add(
                MessageRevision(
                    message_id=current.id,
                    revision=next_revision,
                    text=current.text,
                    entities=current.entities,
                    edited_at=current.edited_at or current.sent_at,
                )
            )
        await db.flush()
        statement = pg_insert(TelegramMessage).values(values)
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            constraint="uq_telegram_messages_chat_msg",
            set_={
                field: getattr(excluded, field)
                for field in (
                    "text",
                    "has_media",
                    "media_type",
                    "media_file_name",
                    "media_mime_type",
                    "media_file_size",
                    "media_duration_seconds",
                    "sender_id",
                    "sender_name",
                    "is_outgoing",
                    "sent_at",
                    "entities",
                    "visible_urls",
                    "hidden_urls",
                    "buttons",
                    "webpage_preview",
                    "reply_to_message_id",
                    "thread_id",
                    "forward_origin",
                    "album_id",
                    "reactions",
                    "edited_at",
                    "poll",
                    "contact",
                    "location",
                    "service_event",
                    "searchable_metadata",
                )
            },
        )
        await db.execute(statement)
        checkpoint = await db.get(MetadataReconciliationCheckpoint, checkpoint_id)
        checkpoint.last_telegram_message_id = last_message_id
        checkpoint.processed_count += len(values)
        checkpoint.updated_at = datetime.now(UTC)
    return len(values)
