"""Typing indicator — show the bot is "thinking" while Claude processes.

Sends a "typing..." action to Telegram so the user sees the bot is working.
Critical for UX: without it, 5-second Claude responses feel like the bot is dead.
"""

import logging
import os

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def send_typing_action(chat_id: int) -> None:
    """Send 'typing' action to Telegram chat.

    This shows "Wai is typing..." in the chat for ~5 seconds.
    Should be called before any slow operation (Claude API, search, etc).
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or get_settings().telegram_bot_token
    if not token:
        return

    url = f"https://api.telegram.org/bot{token}/sendChatAction"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(url, json={"chat_id": chat_id, "action": "typing"})
    except Exception as e:
        logger.debug(f"Typing indicator failed: {e}")
