"""Status command — show user stats and system health.

Displays:
- Messages synced, voice messages transcribed
- Open commitments count
- Search history
- System uptime and model usage
"""

import logging
from uuid import UUID

from app.services.agent.commitments import CommitmentDirection, get_user_commitments
from app.services.agent.metrics import get_metrics

logger = logging.getLogger(__name__)


async def get_user_status(
    user_id: UUID,
    user_name: str | None = None,
    user_language: str = "en",
) -> str:
    """Generate user status display."""
    sections = []

    # Header
    name_part = f" {user_name}" if user_name else ""
    if user_language == "ru":
        sections.append(f"📊 *Статус{name_part}*\n")
    else:
        sections.append(f"📊 *Status{name_part}*\n")

    # Commitments
    i_promised = get_user_commitments(user_id, direction=CommitmentDirection.I_PROMISED)
    they_promised = get_user_commitments(
        user_id, direction=CommitmentDirection.THEY_PROMISED
    )

    if user_language == "ru":
        sections.append(
            f"🤝 Обязательства: {len(i_promised)} ваших, {len(they_promised)} чужих"
        )
    else:
        sections.append(
            f"🤝 Commitments: {len(i_promised)} you promised, {len(they_promised)} others promised"
        )

    # Messages synced (from DB if available)
    try:
        from sqlalchemy import func, select

        from app.core.database import async_session_factory
        from app.models.chat import TelegramChat
        from app.models.message import TelegramMessage

        async with async_session_factory() as db:
            msg_count = await db.scalar(
                select(func.count(TelegramMessage.id))
                .join(TelegramChat)
                .where(TelegramChat.user_id == user_id)
            )
            chat_count = await db.scalar(
                select(func.count(TelegramChat.id)).where(
                    TelegramChat.user_id == user_id
                )
            )
            if msg_count:
                if user_language == "ru":
                    sections.append(f"💬 Сообщений: {msg_count:,} в {chat_count} чатах")
                else:
                    sections.append(f"💬 Messages: {msg_count:,} in {chat_count} chats")
    except Exception:
        pass

    # System metrics
    metrics = get_metrics()
    counters = metrics.get("counters", {})
    total_requests = counters.get("agent_requests_total", 0)
    total_tokens_in = counters.get("agent_tokens_input", 0)
    total_tokens_out = counters.get("agent_tokens_output", 0)
    tool_calls = counters.get("agent_tool_calls", 0)
    uptime = metrics.get("uptime_seconds", 0)

    if user_language == "ru":
        sections.append(
            f"\n⚙️ *Система:*\n"
            f"  Аптайм: {_format_uptime(uptime)}\n"
            f"  Запросов: {total_requests}\n"
            f"  Токенов: {total_tokens_in + total_tokens_out:,}\n"
            f"  Вызовов инструментов: {tool_calls}"
        )
    else:
        sections.append(
            f"\n⚙️ *System:*\n"
            f"  Uptime: {_format_uptime(uptime)}\n"
            f"  Requests: {total_requests}\n"
            f"  Tokens: {total_tokens_in + total_tokens_out:,}\n"
            f"  Tool calls: {tool_calls}"
        )

    return "\n".join(sections)


def _format_uptime(seconds: float) -> str:
    """Format uptime seconds into human-readable string."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}h {minutes}m"
