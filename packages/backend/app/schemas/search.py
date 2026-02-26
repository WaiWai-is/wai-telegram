from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str
    chat_ids: list[UUID] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    limit: int = Field(default=20, ge=1, le=100)


class SearchResultItem(BaseModel):
    id: UUID
    chat_id: UUID
    chat_title: str
    telegram_message_id: int
    text: str | None
    sender_name: str | None
    is_outgoing: bool
    sent_at: datetime
    similarity: float
    has_media: bool = False
    media_type: str | None = None
    transcribed_at: datetime | None = None

    class Config:
        from_attributes = True


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    query: str
    total: int
