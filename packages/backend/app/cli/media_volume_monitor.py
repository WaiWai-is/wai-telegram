import asyncio
import logging
import shutil

import redis.asyncio as aioredis
import sentry_sdk

from app.core.config import get_settings
from app.core.observability import configure_logging, init_observability

logger = logging.getLogger(__name__)


async def check_media_volume() -> dict[str, int | str]:
    settings = get_settings()
    if not settings.media_root.is_mount():
        raise RuntimeError(f"Media root is not a mountpoint: {settings.media_root}")
    usage = shutil.disk_usage(settings.media_root)
    percent = round(usage.used * 100 / usage.total)
    level = "ok"
    if percent >= 95:
        level = "critical"
    elif percent >= 90:
        level = "error"
    elif percent >= 80:
        level = "warning"

    redis = aioredis.from_url(settings.redis_url)
    try:
        key = "media:volume:alert-level"
        prior = await redis.get(key)
        prior_level = prior.decode() if isinstance(prior, bytes) else prior
        if prior_level != level:
            await redis.set(key, level)
            if level != "ok":
                sentry_sdk.capture_message(
                    f"WAI Telegram media volume is {percent}% full",
                    level="warning" if level == "warning" else "error",
                )
    finally:
        await redis.aclose()
    logger.log(
        logging.WARNING if level != "ok" else logging.INFO,
        "Media volume usage: %s%% (%s)",
        percent,
        level,
    )
    return {
        "percent": percent,
        "level": level,
        "free_bytes": usage.free,
        "total_bytes": usage.total,
    }


def main() -> None:
    settings = get_settings()
    configure_logging()
    init_observability(settings, "wai-telegram-media-volume-monitor")
    asyncio.run(check_media_volume())


if __name__ == "__main__":
    main()
