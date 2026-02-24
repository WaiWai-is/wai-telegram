import json
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.database import get_db
from app.models.chat import TelegramChat
from app.models.sync_job import SyncJob, SyncStatus
from app.schemas.sync import SyncJobResponse, SyncProgressResponse
from app.core.limiter import limiter
from app.services.sync_service import create_sync_job
from app.tasks.sync_tasks import sync_chat_task, sync_all_chats_task, redis_client

router = APIRouter()
_RETRY_SECONDS_RE = re.compile(r"retry_after_seconds=(\d+)")


def _parse_retry_after_seconds(error_message: str | None) -> int | None:
    if not error_message:
        return None
    match = _RETRY_SECONDS_RE.search(error_message)
    if not match:
        return None
    return int(match.group(1))


_STALE_JOB_THRESHOLD = timedelta(minutes=15)


async def _expire_stale_jobs(db: AsyncSession, user_id: UUID, chat_id: UUID | None) -> None:
    """Mark IN_PROGRESS jobs as FAILED if no progress for 15 minutes."""
    cutoff = datetime.now(UTC) - _STALE_JOB_THRESHOLD
    query = select(SyncJob).where(
        SyncJob.user_id == user_id,
        SyncJob.status == SyncStatus.IN_PROGRESS,
        SyncJob.updated_at < cutoff,
    )
    if chat_id is not None:
        query = query.where(SyncJob.chat_id == chat_id)
    else:
        query = query.where(SyncJob.chat_id.is_(None))
    stale_jobs = (await db.execute(query)).scalars().all()
    for job in stale_jobs:
        job.status = SyncStatus.FAILED
        job.error_message = "Automatically expired: no progress for 15 minutes"
    if stale_jobs:
        await db.flush()


@router.post("/all", response_model=SyncJobResponse)
@limiter.limit("3/minute")
async def sync_all_chats(
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit_per_chat: int = Query(default=500, ge=0, le=10000),
) -> SyncJobResponse:
    """Start bulk sync of all chats. limit_per_chat=0 means unlimited."""
    # Expire stale jobs before checking for conflicts
    await _expire_stale_jobs(db, user.id, chat_id=None)

    # Check if bulk sync already in progress
    result = await db.execute(
        select(SyncJob).where(
            SyncJob.user_id == user.id,
            SyncJob.chat_id.is_(None),
            SyncJob.status == SyncStatus.IN_PROGRESS,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Bulk sync already in progress")

    job = await create_sync_job(db, user.id, chat_id=None)
    await db.commit()

    sync_all_chats_task.delay(str(user.id), str(job.id), limit_per_chat)

    return SyncJobResponse.model_validate(job)


@router.post("/chats/{chat_id}", response_model=SyncJobResponse)
@limiter.limit("10/minute")
async def sync_chat(
    request: Request,
    chat_id: UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int | None = None,
) -> SyncJobResponse:
    """Start syncing messages for a chat."""
    # Verify chat ownership
    result = await db.execute(
        select(TelegramChat).where(
            TelegramChat.id == chat_id,
            TelegramChat.user_id == user.id,
        )
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

    # Expire stale jobs before checking for conflicts
    await _expire_stale_jobs(db, user.id, chat_id)

    # Check for existing in-progress sync
    result = await db.execute(
        select(SyncJob).where(
            SyncJob.user_id == user.id,
            SyncJob.chat_id == chat_id,
            SyncJob.status == SyncStatus.IN_PROGRESS,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sync already in progress for this chat",
        )

    # Create sync job and commit so worker can find it
    job = await create_sync_job(db, user.id, chat_id)
    await db.commit()

    # Route to listener if active, otherwise to Celery
    if redis_client.get(f"listener:active:{user.id}"):
        redis_client.publish(
            f"listener:cmd:{user.id}",
            json.dumps({
                "command": "sync_chat",
                "user_id": str(user.id),
                "chat_id": str(chat_id),
                "job_id": str(job.id),
                "limit": limit,
            }),
        )
    else:
        sync_chat_task.delay(str(user.id), str(chat_id), str(job.id), limit)

    return SyncJobResponse.model_validate(job)


@router.get("/jobs/{job_id}", response_model=SyncProgressResponse)
async def get_sync_progress(
    job_id: UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SyncProgressResponse:
    """Get sync job progress."""
    result = await db.execute(
        select(SyncJob).where(
            SyncJob.id == job_id,
            SyncJob.user_id == user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    # Get chat title if available
    chat_title = None
    if job.chat_id:
        result = await db.execute(select(TelegramChat).where(TelegramChat.id == job.chat_id))
        chat = result.scalar_one_or_none()
        if chat:
            chat_title = chat.title

    # Calculate progress for bulk sync jobs (chat_id is None)
    progress_percent = None
    chats_completed = None
    total_chats = None
    current_chat_title = chat_title

    if job.chat_id is None:
        total_raw = redis_client.get(f"bulk:{job_id}:total")
        completed_raw = redis_client.get(f"bulk:{job_id}:completed")
        current_raw = redis_client.get(f"bulk:{job_id}:current_chat")

        if total_raw:
            total_chats = int(total_raw.decode())
            chats_completed = int(completed_raw.decode()) if completed_raw else 0
            current_chat_title = current_raw.decode() if current_raw else None
            if total_chats > 0:
                progress_percent = round(chats_completed / total_chats * 100, 1)
    else:
        # Single-chat sync progress from Redis
        total_raw = redis_client.get(f"sync:{job_id}:total")
        seen_raw = redis_client.get(f"sync:{job_id}:seen")
        if total_raw and seen_raw:
            total = int(total_raw.decode())
            seen = int(seen_raw.decode())
            if total > 0:
                progress_percent = min(round(seen / total * 100, 1), 100.0)

    return SyncProgressResponse(
        job_id=job.id,
        status=job.status,
        messages_processed=job.messages_processed,
        current_chat=current_chat_title,
        progress_percent=progress_percent,
        error_message=job.error_message,
        retry_after_seconds=_parse_retry_after_seconds(job.error_message),
        chats_completed=chats_completed,
        total_chats=total_chats,
    )


@router.get("/jobs", response_model=list[SyncJobResponse])
async def list_sync_jobs(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[SyncJobResponse]:
    """List recent sync jobs."""
    result = await db.execute(
        select(SyncJob)
        .where(SyncJob.user_id == user.id)
        .order_by(SyncJob.created_at.desc())
        .limit(limit)
    )
    jobs = result.scalars().all()
    return [SyncJobResponse.model_validate(job) for job in jobs]
