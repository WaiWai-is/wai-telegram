"""Digital Agent model — autonomous AI agents created by users.

Each agent has a schedule (cron), tools, and a system prompt.
Agents run via Celery Beat and send results to the user in Telegram.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DigitalAgent(Base):
    __tablename__ = "digital_agents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger)

    # Agent definition
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    system_prompt: Mapped[str] = mapped_column(Text)
    tools: Mapped[str] = mapped_column(String(500), default="")

    # Schedule
    schedule_type: Mapped[str] = mapped_column(String(20))  # cron, manual
    cron_expression: Mapped[str | None] = mapped_column(String(50))

    # State
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active"
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_result: Mapped[str | None] = mapped_column(Text)

    # Limits
    max_tokens_per_run: Mapped[int] = mapped_column(Integer, default=4096)
    max_runtime_seconds: Mapped[int] = mapped_column(
        Integer, default=300, server_default="300"
    )
    max_tool_turns: Mapped[int] = mapped_column(
        Integer, default=10, server_default="10"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index("ix_digital_agents_user_status", "user_id", "status"),
        Index("ix_digital_agents_next_run", "next_run_at", "status"),
    )
