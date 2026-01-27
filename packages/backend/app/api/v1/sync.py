from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.database import get_db
from app.models.chat import TelegramChat
from app.models.sync_job import SyncJob, SyncStatus
from app.schemas.sync import SyncJobResponse, SyncProgressResponse
from app.services.sync_service import create_sync_job, sync_messages

router = APIRouter()


@router.post("/chats/{chat_id}", response_model=SyncJobResponse)
async def sync_chat(
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

    # Create sync job
    job = await create_sync_job(db, user.id, chat_id)
    job.status = SyncStatus.IN_PROGRESS
    await db.flush()

    try:
        # Run sync (in production, this would be a Celery task)
        await sync_messages(db, user.id, chat_id, job.id, limit)
    except Exception as e:
        job.status = SyncStatus.FAILED
        job.error_message = str(e)
        await db.flush()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

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

    return SyncProgressResponse(
        job_id=job.id,
        status=job.status,
        messages_processed=job.messages_processed,
        current_chat=chat_title,
        progress_percent=None,  # Would need total count for percentage
    )


@router.get("/jobs", response_model=list[SyncJobResponse])
async def list_sync_jobs(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 20,
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
