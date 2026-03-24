"""Morning Briefing — Wai comes to YOU.

Generates a daily briefing from:
1. Yesterday's message summary (from digest service)
2. Open commitments (what you promised, what others promised)
3. Detected entities & topics trending across conversations
4. Upcoming items (if calendar connected)

The [no_message] pattern: if there's nothing worth reporting, stay silent.
"""

import logging
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from app.services.agent.commitments import (
    CommitmentDirection,
    CommitmentStatus,
    get_user_commitments,
)

logger = logging.getLogger(__name__)


async def generate_morning_briefing(
    user_id: UUID,
    user_name: str | None = None,
    user_language: str = "en",
) -> str | None:
    """Generate a morning briefing for the user.

    Returns None if there's nothing worth reporting ([no_message] pattern).
    """
    sections: list[str] = []
    has_content = False

    # Header
    now = datetime.now(UTC)
    if user_language == "ru":
        day_name = _russian_day_name(now.weekday())
        header = f"🌅 *Доброе утро{', ' + user_name if user_name else ''}!*\n_{day_name}, {now.strftime('%d.%m.%Y')}_"
    else:
        header = f"🌅 *Good morning{', ' + user_name if user_name else ''}!*\n_{now.strftime('%A, %B %d, %Y')}_"
    sections.append(header)

    # 1. Open commitments
    all_commitments = get_user_commitments(user_id, status=CommitmentStatus.OPEN)
    i_promised = [
        c for c in all_commitments if c.direction == CommitmentDirection.I_PROMISED
    ]
    they_promised = [
        c for c in all_commitments if c.direction == CommitmentDirection.THEY_PROMISED
    ]

    if i_promised or they_promised:
        has_content = True
        if user_language == "ru":
            sections.append("\n🤝 *Обязательства:*")
        else:
            sections.append("\n🤝 *Open Commitments:*")

        if i_promised:
            for c in i_promised[:5]:
                deadline_text = f" ⏰ {c.deadline}" if c.deadline else ""
                sections.append(f"  📤 {c.what}{deadline_text}")

        if they_promised:
            for c in they_promised[:5]:
                deadline_text = f" ⏰ {c.deadline}" if c.deadline else ""
                sections.append(f"  📥 {c.who}: {c.what}{deadline_text}")

    # 2. Yesterday's digest summary (if available)
    try:
        from app.core.database import async_session_factory
        from app.services.digest_service import generate_digest

        yesterday = date.today() - timedelta(days=1)
        async with async_session_factory() as db:
            digest = await generate_digest(db, user_id, yesterday)
            if digest.content and len(digest.content) > 50:
                has_content = True
                if user_language == "ru":
                    sections.append("\n📊 *Вчера:*")
                else:
                    sections.append("\n📊 *Yesterday:*")
                # Truncate to first 500 chars
                summary = digest.content[:500]
                if len(digest.content) > 500:
                    summary += "..."
                sections.append(summary)
    except Exception as e:
        logger.debug(f"Could not fetch digest for briefing: {e}")

    # 3. [no_message] pattern — if nothing to report, stay silent
    if not has_content:
        return None

    # Footer
    if user_language == "ru":
        sections.append("\n_Хорошего дня! Напиши мне если что-то нужно._")
    else:
        sections.append("\n_Have a great day! Message me if you need anything._")

    return "\n".join(sections)


def _russian_day_name(weekday: int) -> str:
    """Get Russian day name from weekday number (0=Monday)."""
    names = [
        "Понедельник",
        "Вторник",
        "Среда",
        "Четверг",
        "Пятница",
        "Суббота",
        "Воскресенье",
    ]
    return names[weekday] if 0 <= weekday <= 6 else ""


async def should_send_briefing(user_id: UUID) -> bool:
    """Check if a briefing should be sent (the taste function).

    Returns False if:
    - No commitments and no digest → nothing to say
    - Already sent today
    - User is in "do not disturb" mode
    """
    # Check if there are any commitments
    commitments = get_user_commitments(user_id, status=CommitmentStatus.OPEN)
    if commitments:
        return True

    # TODO: Check if there's a digest available
    # TODO: Check if already sent today
    # TODO: Check user's DND settings

    return False
