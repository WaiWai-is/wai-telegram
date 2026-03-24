"""Commitment model — persistent storage for tracked promises.

Stores bi-directional commitments detected from conversations:
- What the user promised others
- What others promised the user
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Commitment(Base):
    __tablename__ = "commitments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    who: Mapped[str] = mapped_column(String(200), nullable=False)
    what: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # i_promised, they_promised, mutual
    deadline: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(20), default="open"
    )  # open, completed, overdue, cancelled
    source_chat: Mapped[str | None] = mapped_column(String(200))
    source_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_commitments_user_status", "user_id", "status"),
        Index("ix_commitments_user_direction", "user_id", "direction"),
    )
