from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    api_key_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_key_prefix: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # Relationships
    telegram_sessions: Mapped[list["TelegramSession"]] = relationship(
        "TelegramSession", back_populates="user", cascade="all, delete-orphan"
    )
    chats: Mapped[list["TelegramChat"]] = relationship(
        "TelegramChat", back_populates="user", cascade="all, delete-orphan"
    )
    sync_jobs: Mapped[list["SyncJob"]] = relationship(
        "SyncJob", back_populates="user", cascade="all, delete-orphan"
    )
    digests: Mapped[list["DailyDigest"]] = relationship(
        "DailyDigest", back_populates="user", cascade="all, delete-orphan"
    )


# Import for type hints
from app.models.chat import TelegramChat  # noqa: E402
from app.models.digest import DailyDigest  # noqa: E402
from app.models.session import TelegramSession  # noqa: E402
from app.models.sync_job import SyncJob  # noqa: E402
