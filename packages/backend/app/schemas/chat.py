from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.chat import ChatType


class ChatResponse(BaseModel):
    id: UUID
    telegram_chat_id: int
    chat_type: ChatType
    title: str
    username: str | None
    last_sync_at: datetime | None
    last_activity_at: datetime | None
    total_messages_synced: int
    created_at: datetime

    class Config:
        from_attributes = True


class ChatListResponse(BaseModel):
    chats: list[ChatResponse]
    total: int
