"""Entry point for the real-time Telegram listener service.

Usage: python -m app.listener.run
"""

import asyncio
import logging

from app.listener.main import TelegramListener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("Starting WAI Telegram Listener")
    listener = TelegramListener()
    asyncio.run(listener.run())


if __name__ == "__main__":
    main()
