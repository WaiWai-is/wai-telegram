from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class MessageResponse(BaseModel):
    id: UUID
    telegram_message_id: int
    text: str | None
    has_media: bool
    media_type: str | None
    media_file_name: str | None = None
    media_mime_type: str | None = None
    media_file_size: int | None = None
    media_duration_seconds: int | None = None
    content_summary: str | None = None
    content_preview: str | None = None
    media_processing_status: str | None = None
    media_processing_error_code: str | None = None
    sender_id: int | None
    sender_name: str | None
    is_outgoing: bool
    sent_at: datetime
    has_embedding: bool
    transcribed_at: datetime | None = None
    telegram_message_url: str | None = None
    media_download_url: str | None = None

    class Config:
        from_attributes = True


class MessageContentResponse(BaseModel):
    id: UUID
    telegram_message_id: int
    text: str | None
    media_type: str | None
    media_file_name: str | None
    media_mime_type: str | None
    media_file_size: int | None
    media_duration_seconds: int | None
    content_text: str | None
    content_summary: str | None
    media_processing_status: str | None
    media_processing_error_code: str | None
    media_processing_error: str | None
    transcribed_at: datetime | None
    media_processed_at: datetime | None
    content_model: str | None
    summary_model: str | None
    telegram_message_url: str | None = None
    media_download_url: str | None = None


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    total: int | None = None
    has_more: bool
    next_cursor: str | None = None
    newest_cursor: str | None = None
    total_messages_synced: int | None = None
    last_sync_at: datetime | None = None
