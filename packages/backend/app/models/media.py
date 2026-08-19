from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MediaStage(StrEnum):
    FETCH = "fetch"
    EXTRACTION = "extraction"
    SUMMARY = "summary"
    INDEX = "index"
    COMPLETE = "complete"


class MediaObjectStatus(StrEnum):
    PENDING = "pending"
    FETCHING = "fetching"
    CACHED = "cached"
    EXTRACTING = "extracting"
    INDEXING = "indexing"
    PROCESSING = "processing"
    READY = "ready"
    READY_DOWNLOAD_ONLY = "ready_download_only"
    RETRY_WAIT = "retry_wait"
    NO_SPEECH = "no_speech"
    SOURCE_DELETED = "source_deleted"
    UNSUPPORTED = "unsupported"
    DISK_FULL = "disk_full"
    FAILED = "failed"


class MediaObject(Base):
    __tablename__ = "media_objects"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("telegram_messages.id", ondelete="CASCADE"), unique=True
    )
    telegram_media_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True)
    relative_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage: Mapped[MediaStage] = mapped_column(
        String(32), default=MediaStage.FETCH, server_default=MediaStage.FETCH.value
    )
    status: Mapped[MediaObjectStatus] = mapped_column(
        String(32),
        default=MediaObjectStatus.PENDING,
        server_default=MediaObjectStatus.PENDING.value,
        index=True,
    )
    byte_offset: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    retry_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcription_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    extracted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    summarized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    message: Mapped["TelegramMessage"] = relationship(
        "TelegramMessage", back_populates="media_object"
    )

    __table_args__ = (
        CheckConstraint(
            "stage IN ('fetch', 'extraction', 'summary', 'index', 'complete')",
            name="ck_media_objects_stage",
        ),
        CheckConstraint(
            "status IN ('pending', 'fetching', 'cached', 'extracting', 'indexing', "
            "'processing', 'ready', 'ready_download_only', 'retry_wait', "
            "'no_speech', 'source_deleted', 'unsupported', 'disk_full', 'failed')",
            name="ck_media_objects_status",
        ),
        CheckConstraint("byte_offset >= 0", name="ck_media_objects_byte_offset"),
        CheckConstraint("retry_count >= 0", name="ck_media_objects_retry_count"),
        Index("ix_media_objects_user_status", "user_id", "status"),
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("telegram_messages.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(BigInteger)
    end_ms: Mapped[int] = mapped_column(BigInteger)
    speaker: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    message: Mapped["TelegramMessage"] = relationship(
        "TelegramMessage", back_populates="transcript_segments"
    )

    __table_args__ = (
        UniqueConstraint(
            "message_id", "sequence", name="uq_transcript_segments_message_sequence"
        ),
        Index(
            "ix_transcript_segments_message_time",
            "message_id",
            "start_ms",
            "end_ms",
        ),
    )


from app.models.message import TelegramMessage  # noqa: E402
