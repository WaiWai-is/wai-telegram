"""Typing indicator — show the bot is thinking during generation.

Sends a "typing..." action to Telegram so the user sees the bot is working.
Critical for UX: without it, multi-second responses feel like the bot is dead.
"""

import logging
from app.services.telegram_bot_api import get_bot_api_client

logger = logging.getLogger(__name__)


async def send_typing_action(chat_id: int) -> None:
    """Send 'typing' action to Telegram chat.

    This shows "Wai is typing..." in the chat for ~5 seconds.
    Should be called before any slow operation (generation, search, etc).
    """
    try:
        await get_bot_api_client().call(
            "sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=5,
        )
    except Exception as e:
        logger.debug("Typing indicator failed (%s)", type(e).__name__)
