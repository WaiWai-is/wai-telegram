import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from celery import shared_task
from sqlalchemy import and_, case, func, or_, select, update

from app.core.async_runner import run_async
from app.core.config import get_settings
from app.core.database import get_db_context
from app.models.message import MediaProcessingStatus, TelegramMessage
from app.services.media_processing_service import process_media_message

logger = logging.getLogger(__name__)
settings = get_settings()


def enqueue_media_processing(message_ids: list[UUID]) -> None:
    """Send durable media jobs to the isolated, low-prefetch media queue."""
    for message_id in message_ids:
        process_message_media_task.apply_async(
            args=[str(message_id)],
            queue="media",
        )


@shared_task(max_retries=0, name="app.tasks.media_tasks.process_message_media")
def process_message_media_task(message_id: str) -> dict[str, str]:
    """Process once; provider failures are persisted and never auto-retried."""
    message_uuid = UUID(message_id)
    status = run_async(process_media_message(message_uuid))
    return {"message_id": message_id, "status": status}


async def _find_pending_and_reap_stale() -> list[UUID]:
    now = datetime.now(UTC)
    queued_before = now - timedelta(minutes=settings.media_queue_stale_minutes)
    stale_before = now - timedelta(minutes=settings.media_processing_stale_minutes)
    async with get_db_context() as db:
        # Recover only very old dispatch claims. Normal broker backlog remains
        # queued; duplicate delivery is still protected by the processing claim.
        await db.execute(
            update(TelegramMessage)
            .where(
                TelegramMessage.media_processing_status == MediaProcessingStatus.QUEUED,
                TelegramMessage.media_processing_started_at < queued_before,
            )
            .values(
                media_processing_status=MediaProcessingStatus.PENDING,
                media_processing_started_at=None,
            )
        )
        stale_ids = list(
            (
                await db.execute(
                    update(TelegramMessage)
                    .where(
                        TelegramMessage.media_processing_status
                        == MediaProcessingStatus.PROCESSING,
                        TelegramMessage.media_processing_started_at < stale_before,
                    )
                    .values(
                        media_processing_status=MediaProcessingStatus.FAILED,
                        media_processing_error_code="worker_interrupted",
                        media_processing_error=(
                            "Background worker stopped before processing completed"
                        ),
                        media_processed_at=now,
                    )
                    .returning(TelegramMessage.id)
                )
            )
            .scalars()
            .all()
        )
        active_count = (
            await db.execute(
                select(func.count()).where(
                    TelegramMessage.media_processing_status.in_(
                        (
                            MediaProcessingStatus.QUEUED,
                            MediaProcessingStatus.PROCESSING,
                        )
                    )
                )
            )
        ).scalar_one()
        dispatch_limit = max(
            0,
            settings.media_dispatch_target_depth - active_count,
        )
        if dispatch_limit == 0:
            return []

        live_priority = case(
            (
                TelegramMessage.media_processing_status
                == MediaProcessingStatus.PENDING,
                0,
            ),
            else_=1,
        )
        media_priority = case(
            (TelegramMessage.transcribed_at.isnot(None), 0),
            (
                TelegramMessage.media_type.in_(
                    ("voice", "video_note", "audio", "video")
                ),
                1,
            ),
            (TelegramMessage.media_type == "document", 2),
            (TelegramMessage.media_type == "photo", 3),
            else_=4,
        )
        eligible_uninitialized = and_(
            TelegramMessage.media_processing_status.is_(None),
            TelegramMessage.has_media.is_(True),
            TelegramMessage.media_type.in_(
                ("voice", "video_note", "audio", "video", "photo", "document")
            ),
        )
        dispatchable = or_(
            TelegramMessage.media_processing_status == MediaProcessingStatus.PENDING,
            eligible_uninitialized,
        )
        pending_subquery = (
            select(TelegramMessage.id)
            .where(dispatchable)
            .order_by(
                live_priority.asc(),
                media_priority.asc(),
                TelegramMessage.sent_at.desc(),
                TelegramMessage.id.desc(),
            )
            .limit(dispatch_limit)
            .with_for_update(skip_locked=True)
        )
        pending_ids = list(
            (
                await db.execute(
                    update(TelegramMessage)
                    .where(
                        TelegramMessage.id.in_(pending_subquery),
                        dispatchable,
                    )
                    .values(
                        media_processing_status=MediaProcessingStatus.QUEUED,
                        media_processing_started_at=now,
                    )
                    .returning(TelegramMessage.id)
                )
            )
            .scalars()
            .all()
        )

    if stale_ids:
        logger.error(
            "Marked %s interrupted media jobs as failed",
            len(stale_ids),
        )
    return pending_ids


async def _return_queued_to_pending(message_ids: list[UUID]) -> None:
    if not message_ids:
        return
    async with get_db_context() as db:
        await db.execute(
            update(TelegramMessage)
            .where(
                TelegramMessage.id.in_(message_ids),
                TelegramMessage.media_processing_status == MediaProcessingStatus.QUEUED,
            )
            .values(
                media_processing_status=MediaProcessingStatus.PENDING,
                media_processing_started_at=None,
            )
        )


@shared_task(max_retries=0, name="app.tasks.media_tasks.dispatch_pending_media")
def dispatch_pending_media() -> dict[str, int]:
    """Recover pending jobs missed by immediate dispatch after ingestion."""
    message_ids = run_async(_find_pending_and_reap_stale())
    for index, message_id in enumerate(message_ids):
        try:
            enqueue_media_processing([message_id])
        except Exception:
            run_async(_return_queued_to_pending(message_ids[index:]))
            raise
    return {"dispatched": len(message_ids)}
