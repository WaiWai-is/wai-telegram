import logging

from app.services.telegram_bot_api import get_bot_api_client

logger = logging.getLogger(__name__)
MAX_MESSAGE_LENGTH = 4096


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
    chunks = _split_message(text)
    client = get_bot_api_client()
    for chunk in chunks:
        await client.call(
            "sendMessage",
            json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": parse_mode,
            },
        )


async def send_telegram_photo(chat_id: int, photo_url: str, caption: str = "") -> bool:
    """Send a photo via Telegram Bot API.

    No parse_mode — captions are plain text to avoid Markdown 400 errors.
    Returns True on success, False if the photo send failed.
    """
    payload: dict = {
        "chat_id": chat_id,
        "photo": photo_url,
    }
    if caption:
        payload["caption"] = caption

    await get_bot_api_client().call("sendPhoto", json=payload)
    return True
