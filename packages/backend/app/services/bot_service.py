import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_MESSAGE_LENGTH = 4096


def _redact(text: str) -> str:
    """Strip the bot token from text so it never reaches logs or Sentry."""
    token = settings.telegram_bot_token
    if token and token in text:
        text = text.replace(token, "***")
    return text


def _split_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split text into chunks that fit within Telegram's message limit."""
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        # Try to split at last newline within limit
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


async def send_telegram_message(
    chat_id: int, text: str, parse_mode: str = "Markdown"
) -> None:
    """Send a message via Telegram Bot API. Splits long messages automatically."""
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured")

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    chunks = _split_message(text)

    async with httpx.AsyncClient(timeout=30) as client:
        for chunk in chunks:
            resp = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": parse_mode,
                },
            )
            # If Markdown/HTML parsing fails, retry as plain text
            if resp.status_code == 400 and parse_mode:
                resp = await client.post(
                    url,
                    json={"chat_id": chat_id, "text": chunk},
                )
            # Raise a token-free error: httpx's raise_for_status() would embed the
            # full request URL (including the bot token) in the exception message.
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Telegram sendMessage failed with status {resp.status_code}: "
                    f"{_redact(resp.text)[:200]}"
                )


async def send_telegram_photo(chat_id: int, photo_url: str, caption: str = "") -> bool:
    """Send a photo via Telegram Bot API.

    No parse_mode — captions are plain text to avoid Markdown 400 errors.
    Returns True on success, False if the photo send failed.
    """
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured")

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendPhoto"
    payload: dict = {
        "chat_id": chat_id,
        "photo": photo_url,
    }
    if caption:
        payload["caption"] = caption

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True
            logger.warning(
                f"sendPhoto failed ({resp.status_code}): {_redact(resp.text)[:200]}"
            )
            return False
    except Exception as e:
        logger.warning(f"sendPhoto error: {_redact(str(e))}")
        return False
