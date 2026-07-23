from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.core.database import Base

settings = get_settings()


class MediaProcessingStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


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
    media_file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    media_mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    media_file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    media_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_processing_status: Mapped[MediaProcessingStatus | None] = mapped_column(
        Enum(
            MediaProcessingStatus,
            name="media_processing_status",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda members: [member.value for member in members],
        ),
        nullable=True,
        index=True,
    )
    media_processing_error_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    media_processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_processing_attempts: Mapped[int] = mapped_column(Integer, default=0)
    media_processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    media_processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    summary_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sender_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_outgoing: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dimensions), nullable=True
    )
    embedded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    transcribed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # Relationships
    chat: Mapped["TelegramChat"] = relationship(
        "TelegramChat", back_populates="messages"
    )
    content_chunks: Mapped[list["MessageContentChunk"]] = relationship(
        "MessageContentChunk",
        back_populates="message",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "chat_id", "telegram_message_id", name="uq_telegram_messages_chat_msg"
        ),
        Index("ix_telegram_messages_chat_sent", "chat_id", "sent_at"),
        Index(
            "ix_telegram_messages_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class MessageContentChunk(Base):
    __tablename__ = "message_content_chunks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("telegram_messages.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dimensions), nullable=True
    )
    embedded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    message: Mapped[TelegramMessage] = relationship(
        "TelegramMessage", back_populates="content_chunks"
    )

    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "chunk_index",
            name="uq_message_content_chunks_message_index",
        ),
        Index(
            "ix_message_content_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


from app.models.chat import TelegramChat  # noqa: E402
