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
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import TSVECTOR

from app.core.config import get_settings
from app.core.database import Base

settings = get_settings()


class MediaProcessingStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    # Settled, but nothing was extractable: the sender deleted the file, or the
    # recording carries no speech. Distinct from FAILED so these are never retried
    # and never counted as errors needing attention.
    SKIPPED = "skipped"


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
    entities: Mapped[list | None] = mapped_column(JSON, nullable=True)
    visible_urls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    hidden_urls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    buttons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    webpage_preview: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reply_to_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    thread_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    forward_origin: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    album_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reactions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    poll: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    contact: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    location: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    service_event: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    searchable_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR().with_variant(Text(), "sqlite"), nullable=True
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
    media_object: Mapped["MediaObject | None"] = relationship(
        "MediaObject", back_populates="message", uselist=False
    )
    transcript_segments: Mapped[list["TranscriptSegment"]] = relationship(
        "TranscriptSegment",
        back_populates="message",
        cascade="all, delete-orphan",
    )
    revisions: Mapped[list["MessageRevision"]] = relationship(
        "MessageRevision",
        back_populates="message",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "chat_id", "telegram_message_id", name="uq_telegram_messages_chat_msg"
        ),
        Index("ix_telegram_messages_chat_sent", "chat_id", "sent_at"),
        Index(
            "ix_telegram_messages_search_vector_gin",
            "search_vector",
            postgresql_using="gin",
        ),
        Index(
            "ix_telegram_messages_media_file_name_trgm",
            "media_file_name",
            postgresql_using="gin",
            postgresql_ops={"media_file_name": "gin_trgm_ops"},
        ),
        Index(
            "ix_telegram_messages_searchable_metadata_trgm",
            "searchable_metadata",
            postgresql_using="gin",
            postgresql_ops={"searchable_metadata": "gin_trgm_ops"},
        ),
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
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR().with_variant(Text(), "sqlite"), nullable=True
    )
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
            "ix_message_content_chunks_search_vector_gin",
            "search_vector",
            postgresql_using="gin",
        ),
        Index(
            "ix_message_content_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class MessageRevision(Base):
    __tablename__ = "message_revisions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("telegram_messages.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    entities: Mapped[list | None] = mapped_column(JSON, nullable=True)
    edited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    message: Mapped["TelegramMessage"] = relationship(
        "TelegramMessage", back_populates="revisions"
    )

    __table_args__ = (
        UniqueConstraint(
            "message_id", "revision", name="uq_message_revisions_message_revision"
        ),
    )


from app.models.chat import TelegramChat  # noqa: E402
from app.models.media import MediaObject, TranscriptSegment  # noqa: E402
