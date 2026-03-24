"""User Resolver — map Telegram user IDs to internal user IDs.

When a message arrives from Telegram, we need to find the corresponding
internal user. The mapping is: telegram_sessions.telegram_user_id → users.id.

For users who haven't connected yet, we auto-create a user record
so they can start using the bot immediately (onboarding later).
"""

import logging
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import TelegramSession
from app.models.user import User

logger = logging.getLogger(__name__)

# In-memory cache: telegram_user_id → internal user_id
_cache: dict[int, UUID] = {}


async def resolve_user_id(
    db: AsyncSession,
    telegram_user_id: int,
    telegram_username: str | None = None,
) -> UUID:
    """Resolve a Telegram user ID to an internal user ID.

    Lookup chain:
    1. In-memory cache (instant)
    2. DB: telegram_sessions.telegram_user_id → user_id
    3. Auto-create: new user record if not found

    Returns the internal user UUID.
    """
    # 1. Cache check
    if telegram_user_id in _cache:
        return _cache[telegram_user_id]

    # 2. DB lookup via telegram_sessions
    result = await db.execute(
        select(TelegramSession.user_id).where(
            TelegramSession.telegram_user_id == telegram_user_id,
            TelegramSession.is_active.is_(True),
        )
    )
    row = result.scalar_one_or_none()

    if row:
        _cache[telegram_user_id] = row
        return row

    # 3. Check if there's a user with matching email pattern (bot-created users)
    bot_email = f"tg_{telegram_user_id}@wai.bot"
    result = await db.execute(select(User.id).where(User.email == bot_email))
    existing_id = result.scalar_one_or_none()

    if existing_id:
        _cache[telegram_user_id] = existing_id
        return existing_id

    # 4. Auto-create user for immediate bot usage
    new_user = User(
        id=uuid4(),
        email=bot_email,
        password_hash="bot-user-no-password",  # Bot users don't need password
    )
    db.add(new_user)
    await db.flush()

    _cache[telegram_user_id] = new_user.id
    logger.info(f"Auto-created user for Telegram ID {telegram_user_id}: {new_user.id}")
    return new_user.id


def clear_cache() -> None:
    """Clear the user resolution cache (for testing)."""
    _cache.clear()
