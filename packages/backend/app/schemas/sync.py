from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.sync_job import SyncStatus


class SyncJobResponse(BaseModel):
    id: UUID
    chat_id: UUID | None
    status: SyncStatus
    messages_processed: int
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None

    class Config:
        from_attributes = True


class SyncProgressResponse(BaseModel):
    job_id: UUID
    status: SyncStatus
    messages_processed: int
    current_chat: str | None
    progress_percent: float | None
    error_message: str | None
    retry_after_seconds: int | None = None
    chats_completed: int | None = None
    total_chats: int | None = None
    messages_total: int | None = None
    messages_seen: int | None = None
