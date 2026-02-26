from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class MessageResponse(BaseModel):
    id: UUID
    telegram_message_id: int
    text: str | None
    has_media: bool
    media_type: str | None
    sender_id: int | None
    sender_name: str | None
    is_outgoing: bool
    sent_at: datetime
    has_embedding: bool
    transcribed_at: datetime | None = None

    class Config:
        from_attributes = True


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    total: int | None = None
    has_more: bool
    next_cursor: str | None = None
