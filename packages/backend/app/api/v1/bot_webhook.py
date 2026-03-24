"""Telegram Bot Webhook — receives messages and routes to the agent system.

This is the entry point for all user interactions with @wai_bot.
Messages come in via Telegram's webhook API, get processed by the agent,
and responses are sent back.
"""

import hashlib
import logging
import os
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.services.agent.loop import AgentContext, AgentResult, run_agent
from app.services.bot_service import send_telegram_message

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_bot_token() -> str:
    """Get bot token — env var takes precedence over settings (avoids LRU cache issues)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        token = get_settings().telegram_bot_token
    return token


def _webhook_secret() -> str:
    """Generate webhook URL secret from bot token hash."""
    token = _get_bot_token()
    if not token:
        return "no-token"
    return hashlib.sha256(token.encode()).hexdigest()[:32]


@router.post("/webhook/{secret}")
async def bot_webhook(secret: str, request: Request) -> JSONResponse:
    """Handle incoming Telegram bot updates.

    This endpoint receives all messages sent to @wai_bot and routes them
    through the agent system.
    """
    # Verify webhook secret
    if secret != _webhook_secret():
        return JSONResponse({"error": "invalid secret"}, status_code=403)

    update = await request.json()
    logger.info(f"Bot webhook update: {update.get('update_id')}")

    # Process in background (don't block Telegram's webhook)
    # For now, process synchronously; later move to Celery
    try:
        await _process_update(update)
    except Exception as e:
        logger.error(f"Error processing bot update: {e}", exc_info=True)

    return JSONResponse({"ok": True})


async def _process_update(update: dict) -> None:
    """Process a single Telegram update."""
    message = update.get("message")
    if not message:
        return

    chat_id = message["chat"]["id"]
    from_user = message.get("from", {})
    user_name = from_user.get("first_name", "")
    text = message.get("text", "")
    voice = message.get("voice")
    # Handle voice messages
    voice_transcript = None
    has_voice = False
    if voice:
        has_voice = True
        voice_transcript = await _transcribe_voice(message)
        if not text:
            text = ""

    # Handle /start command
    if text.strip() == "/start":
        await send_telegram_message(
            chat_id,
            "👋 *Hey! I'm Wai* — your AI partner in Telegram.\n\n"
            "I can:\n"
            "🔍 Search your past messages by meaning\n"
            "🎤 Transcribe & summarize voice messages\n"
            "📋 Track commitments people made\n"
            "📊 Generate daily digests\n"
            "🚀 Build & deploy sites\n\n"
            "Just talk to me naturally, or try:\n"
            "• Forward a voice message\n"
            "• `/search what did Alex say about pricing`\n"
            "• `/digest` for today's summary\n\n"
            "To connect your Telegram history, visit the Mini App ⬇️",
        )
        return

    # Skip empty messages
    if not text and not has_voice:
        return

    # Build agent context
    # TODO: Load real user data from DB, load conversation history, load memories
    context = AgentContext(
        user_id=UUID("00000000-0000-0000-0000-000000000000"),  # Placeholder
        chat_id=chat_id,
        user_name=user_name,
        user_language=_detect_language(text or voice_transcript or ""),
        has_voice=has_voice,
        voice_transcript=voice_transcript,
    )

    # Run the agent
    result: AgentResult = await run_agent(context, text)

    # Send response
    await send_telegram_message(chat_id, result.response)

    logger.info(
        f"Agent response: intent={result.intent.value}, model={result.model_used}, "
        f"tokens={result.input_tokens}+{result.output_tokens}, tools={result.tool_calls}"
    )


async def _transcribe_voice(message: dict) -> str | None:
    """Transcribe a voice message using Deepgram."""
    try:
        from app.services.transcription_service import transcribe_voice_message

        # Download voice file from Telegram
        voice = message["voice"]
        file_id = voice["file_id"]

        import httpx

        # Get file path from Telegram
        bot_token = _get_bot_token()
        url = f"https://api.telegram.org/bot{bot_token}/getFile"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params={"file_id": file_id})
            file_path = resp.json()["result"]["file_path"]

            # Download the file
            download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
            audio_resp = await client.get(download_url)
            audio_data = audio_resp.content

        # Transcribe with Deepgram
        transcript = await transcribe_voice_message(audio_data)
        return transcript
    except Exception as e:
        logger.error(f"Voice transcription failed: {e}", exc_info=True)
        return None


def _detect_language(text: str) -> str:
    """Simple language detection based on character ranges."""
    cyrillic_count = sum(1 for c in text if "\u0400" <= c <= "\u04ff")
    if cyrillic_count > len(text) * 0.3:
        return "ru"
    return "en"
