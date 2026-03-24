"""Bot Rate Limiter — prevent abuse while keeping it lovable.

Limits per user:
- 30 messages per minute (generous for normal use)
- 200 messages per hour (prevents runaway loops)
- Friendly message when limit hit (not a cold error)

Philosophy: rate limits should be invisible to normal users.
Only abusers/bots should ever see them.
"""

import logging
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

# Per-user sliding window rate limiter
_windows: dict[int, list[float]] = defaultdict(list)

MINUTE_LIMIT = 30
HOUR_LIMIT = 200


def check_rate_limit(telegram_user_id: int) -> bool:
    """Check if a user is within rate limits.

    Returns True if the request is allowed, False if rate-limited.
    """
    now = time.monotonic()
    timestamps = _windows[telegram_user_id]

    # Clean old entries (older than 1 hour)
    _windows[telegram_user_id] = [t for t in timestamps if now - t < 3600]
    timestamps = _windows[telegram_user_id]

    # Check hour limit
    if len(timestamps) >= HOUR_LIMIT:
        logger.warning(f"Rate limit (hour): user {telegram_user_id}")
        return False

    # Check minute limit
    recent = [t for t in timestamps if now - t < 60]
    if len(recent) >= MINUTE_LIMIT:
        logger.warning(f"Rate limit (minute): user {telegram_user_id}")
        return False

    # Record this request
    _windows[telegram_user_id].append(now)
    return True


def get_rate_limit_message(user_language: str = "en") -> str:
    """Get a friendly rate limit message."""
    if user_language == "ru":
        return "⏳ Слишком много сообщений. Подожди немного и попробуй снова."
    return "⏳ Too many messages. Please wait a moment and try again."


def clear_rate_limits() -> None:
    """Clear all rate limits (for testing)."""
    _windows.clear()
