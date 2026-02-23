"""Redis-based rate budget tracking for Telegram API calls."""

import logging

import redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_redis: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url)
    return _redis


def record_request() -> None:
    """Record a Telegram API request against hourly and daily budgets."""
    r = _get_redis()
    pipe = r.pipeline()

    hourly_key = "tg:rate:hourly"
    daily_key = "tg:rate:daily"

    pipe.incr(hourly_key)
    pipe.expire(hourly_key, 3600)  # Reset every hour
    pipe.incr(daily_key)
    pipe.expire(daily_key, 86400)  # Reset every day

    pipe.execute()


def get_budget_status() -> dict:
    """Get current rate budget usage."""
    r = _get_redis()
    hourly = int(r.get("tg:rate:hourly") or 0)
    daily = int(r.get("tg:rate:daily") or 0)
    return {
        "hourly_used": hourly,
        "hourly_limit": settings.rate_budget_hourly,
        "hourly_remaining": max(0, settings.rate_budget_hourly - hourly),
        "daily_used": daily,
        "daily_limit": settings.rate_budget_daily,
        "daily_remaining": max(0, settings.rate_budget_daily - daily),
    }


def check_budget() -> bool:
    """Check if we're within rate budget. Returns True if safe to proceed."""
    status = get_budget_status()
    if status["hourly_remaining"] <= 0:
        logger.warning(f"Hourly rate budget exhausted: {status['hourly_used']}/{status['hourly_limit']}")
        return False
    if status["daily_remaining"] <= 0:
        logger.warning(f"Daily rate budget exhausted: {status['daily_used']}/{status['daily_limit']}")
        return False
    return True
