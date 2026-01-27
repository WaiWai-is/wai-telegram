from datetime import UTC, datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.config import get_settings

settings = get_settings()


class TelegramMessage(Base):
    __tablename__ = "telegram_messages"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("telegram_chats.id", ondelete="CASCADE"), index=True
    )
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, index=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_media: Mapped[bool] = mapped_column(Boolean, default=False)
    media_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sender_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_outgoing: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dimensions), nullable=True
    )
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # Relationships
    chat: Mapped["TelegramChat"] = relationship("TelegramChat", back_populates="messages")

    __table_args__ = (
        Index("ix_telegram_messages_chat_sent", "chat_id", "sent_at"),
        Index(
            "ix_telegram_messages_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


from app.models.chat import TelegramChat  # noqa: E402
