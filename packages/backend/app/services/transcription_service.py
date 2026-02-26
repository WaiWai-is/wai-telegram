import io
import logging
from datetime import UTC, datetime

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

TRANSCRIBABLE_MEDIA_TYPES = {"voice", "video_note"}

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25MB limit


async def transcribe_audio(audio_bytes: bytes) -> str:
    """Transcribe audio bytes using DeepGram Nova-3."""
    from deepgram import AsyncDeepgramClient

    client = AsyncDeepgramClient(api_key=settings.deepgram_api_key)
    response = await client.listen.v1.media.transcribe_file(
        request=audio_bytes,
        model=settings.deepgram_model,
        smart_format=True,
        detect_language=True,
    )
    channels = getattr(getattr(response, "results", None), "channels", None)
    if not channels:
        return ""
    alternatives = getattr(channels[0], "alternatives", None)
    if not alternatives:
        return ""
    return alternatives[0].transcript or ""


async def download_and_transcribe(telethon_client, message) -> str | None:
    """Download voice/video_note from Telegram and transcribe it.

    Returns None if DeepGram key is not configured.
    Raises on transcription failures.
    """
    if not settings.deepgram_api_key:
        return None

    buffer = io.BytesIO()
    await telethon_client.download_media(message, file=buffer)
    audio_bytes = buffer.getvalue()

    if not audio_bytes:
        logger.warning("Downloaded empty audio for message %s", message.id)
        return None

    if len(audio_bytes) > MAX_AUDIO_BYTES:
        logger.warning(
            "Audio too large (%d bytes) for message %s, skipping",
            len(audio_bytes),
            message.id,
        )
        return None

    transcript = await transcribe_audio(audio_bytes)
    return transcript if transcript else None
