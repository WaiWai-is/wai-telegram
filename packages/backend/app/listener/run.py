"""Entry point for the real-time Telegram listener service.

Usage: python -m app.listener.run
"""

import asyncio
import logging

from app.core.config import get_settings
from app.core.observability import (
    build_runtime_summary,
    configure_logging,
    init_observability,
    log_event,
)
from app.listener.main import TelegramListener

configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()
init_observability(settings, "wai-telegram-listener")


def main():
    log_event(
        logger,
        logging.INFO,
        "Starting WAI Telegram Listener",
        event_name="listener.bootstrap",
        **build_runtime_summary(
            service_name="wai-telegram-listener",
            settings=settings,
        ),
    )
    listener = TelegramListener()
    asyncio.run(listener.run())


if __name__ == "__main__":
    main()
