from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

import enum


class ChatType(str, enum.Enum):
    PRIVATE = "private"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


class TelegramChat(Base):
    __tablename__ = "telegram_chats"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    chat_type: Mapped[ChatType] = mapped_column(Enum(ChatType))
    title: Mapped[str] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_messages_synced: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="chats")
    messages: Mapped[list["TelegramMessage"]] = relationship(
        "TelegramMessage", back_populates="chat", cascade="all, delete-orphan"
    )
    sync_jobs: Mapped[list["SyncJob"]] = relationship(
        "SyncJob", back_populates="chat", cascade="all, delete-orphan"
    )


from app.models.message import TelegramMessage  # noqa: E402
from app.models.sync_job import SyncJob  # noqa: E402
from app.models.user import User  # noqa: E402
