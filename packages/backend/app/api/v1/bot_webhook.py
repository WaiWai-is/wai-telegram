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
    # Handle voice messages — the #1 wow moment
    voice_transcript = None
    has_voice = False
    if voice:
        has_voice = True
        voice_transcript = await _transcribe_voice(message)
        if voice_transcript:
            # Direct voice summary (skip agent loop for speed)
            from app.services.agent.voice_summary import summarize_voice

            summary = await summarize_voice(voice_transcript, user_name=user_name)
            await send_telegram_message(chat_id, summary)
            logger.info(
                f"Voice summary sent: {len(voice_transcript)} chars transcript, "
                f"user={from_user.get('id')}"
            )
            return
        else:
            await send_telegram_message(
                chat_id,
                "❌ Could not transcribe this voice message. "
                "Try sending a clearer recording.",
            )
            return

    # Handle /start and /help commands
    if text.strip() in ("/start", "/help"):
        lang = _detect_language(text)
        if lang == "ru" or (
            user_name
            and any(c in user_name for c in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
        ):
            await send_telegram_message(
                chat_id,
                "👋 *Привет! Я Wai* — твой AI-партнёр в Telegram.\n\n"
                "Я умею:\n"
                "🔍 Искать по прошлым сообщениям по смыслу\n"
                "🎤 Транскрибировать и резюмировать голосовые\n"
                "📋 Отслеживать обещания (свои и чужие)\n"
                "📊 Генерировать ежедневные дайджесты\n"
                "🧠 Извлекать людей, решения, суммы из текста\n"
                "🌅 Утренний брифинг с обязательствами\n\n"
                "Просто пиши мне или попробуй:\n"
                "• Перешли голосовое сообщение\n"
                "• `/search что обсуждали с Алексом`\n"
                "• `/commitments` — открытые обещания\n"
                "• `/entities текст` — извлечь сущности\n"
                "• `/briefing` — утренний брифинг\n"
                "• `/digest` — дайджест дня",
            )
        else:
            await send_telegram_message(
                chat_id,
                "👋 *Hey! I'm Wai* — your AI partner in Telegram.\n\n"
                "I can:\n"
                "🔍 Search past messages by meaning\n"
                "🎤 Transcribe & summarize voice messages\n"
                "📋 Track commitments (yours & others')\n"
                "📊 Generate daily digests\n"
                "🧠 Extract people, decisions, amounts from text\n"
                "🌅 Morning briefing with open commitments\n\n"
                "Just talk to me naturally, or try:\n"
                "• Forward a voice message\n"
                "• `/search what did Alex say about pricing`\n"
                "• `/commitments` — open promises\n"
                "• `/entities <text>` — extract entities\n"
                "• `/briefing` — morning briefing\n"
                "• `/digest` — daily summary",
            )
        return

    # Handle /briefing command
    if text.strip().startswith("/briefing"):
        from app.services.agent.briefing import generate_morning_briefing

        user_id = UUID("00000000-0000-0000-0000-000000000000")
        lang = _detect_language(user_name or text)
        briefing = await generate_morning_briefing(
            user_id, user_name=user_name, user_language=lang
        )
        if briefing:
            await send_telegram_message(chat_id, briefing)
        else:
            if lang == "ru":
                await send_telegram_message(
                    chat_id, "🌅 Нет ничего важного для брифинга. Хороший знак!"
                )
            else:
                await send_telegram_message(
                    chat_id, "🌅 Nothing important to brief you on. That's a good sign!"
                )
        return

    # Handle /commitments command
    if text.strip().startswith("/commitments"):
        from app.services.agent.commitments import (
            format_commitments_for_display,
            get_user_commitments,
        )

        user_id = UUID("00000000-0000-0000-0000-000000000000")  # Placeholder
        commitments = get_user_commitments(user_id)
        response = format_commitments_for_display(commitments)
        await send_telegram_message(chat_id, response)
        return

    # Handle /entities command (extract from forwarded/replied message)
    if text.strip().startswith("/entities"):
        from app.services.agent.entities import (
            extract_entities_fast,
            format_entities_for_display,
        )

        entity_text = text.replace("/entities", "").strip()
        if entity_text:
            entities = extract_entities_fast(entity_text)
            response = format_entities_for_display(entities)
        else:
            response = "Send `/entities <text>` to extract people, decisions, amounts from text."
        await send_telegram_message(chat_id, response)
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
    """Detect language using the full language detection service."""
    from app.services.agent.language import detect_language

    return detect_language(text)
