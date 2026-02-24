from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )

    # Digest
    digest_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    digest_hour_utc: Mapped[int] = mapped_column(SmallInteger, default=9)
    digest_telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # Auto-sync
    auto_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=1440)

    # Real-time
    realtime_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="settings")


from app.models.user import User  # noqa: E402
