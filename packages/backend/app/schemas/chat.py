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
    last_message_id: int | None = None
    last_sync_at: datetime | None
    last_activity_at: datetime | None
    total_messages_synced: int
    last_message_text: str | None = None
    last_message_sender_name: str | None = None
    unread_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class ChatListResponse(BaseModel):
    chats: list[ChatResponse]
    has_more: bool = False
    next_cursor: str | None = None
    total: int | None = None
