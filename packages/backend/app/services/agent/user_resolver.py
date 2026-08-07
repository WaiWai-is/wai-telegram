"""User Resolver — map Telegram user IDs to internal user IDs.

When a message arrives from Telegram, we need to find the corresponding
internal user. The mapping is: telegram_sessions.telegram_user_id → users.id.

Unknown senders are deliberately ignored. The bot is a private single-user surface.
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.session import TelegramSession
from app.models.user import User

logger = logging.getLogger(__name__)

# In-memory cache: telegram_user_id → internal user_id
_cache: dict[int, UUID] = {}
settings = get_settings()


async def resolve_user_id(
    db: AsyncSession,
    telegram_user_id: int,
    telegram_username: str | None = None,
) -> UUID | None:
    """Resolve a Telegram user ID to an internal user ID.

    Every lookup re-checks both session and owner activity so deactivation takes
    effect immediately even if this process previously saw the sender.
    """
    conditions = [
        TelegramSession.telegram_user_id == telegram_user_id,
        TelegramSession.is_active.is_(True),
        User.is_active.is_(True),
    ]
    if settings.owner_user_id is not None:
        conditions.append(User.id == settings.owner_user_id)

    result = await db.execute(
        select(TelegramSession.user_id)
        .join(User, User.id == TelegramSession.user_id)
        .where(*conditions)
    )
    row = result.scalar_one_or_none()

    if row is None:
        logger.info("Ignored Telegram update from an unknown sender")
        return None

    _cache[telegram_user_id] = row
    return row


def clear_cache() -> None:
    """Clear the user resolution cache (for testing)."""
    _cache.clear()
