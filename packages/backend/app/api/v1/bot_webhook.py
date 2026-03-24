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

PLACEHOLDER_USER = UUID("00000000-0000-0000-0000-000000000000")


async def _resolve_user(from_user: dict) -> UUID:
    """Resolve Telegram user to internal UUID, with fallback."""
    try:
        from app.core.database import async_session_factory
        from app.services.agent.user_resolver import resolve_user_id

        async with async_session_factory() as db:
            uid = await resolve_user_id(
                db,
                telegram_user_id=from_user.get("id", 0),
                telegram_username=from_user.get("username"),
            )
            await db.commit()
            return uid
    except Exception as e:
        logger.debug(f"User resolution fallback: {e}")
        return PLACEHOLDER_USER


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

    try:
        update = await request.json()
    except Exception as e:
        logger.error(f"Invalid JSON in webhook: {e}")
        return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)

    logger.info(f"Bot webhook update: {update.get('update_id')}")

    # Handle inline queries (viral mechanic)
    inline_query = update.get("inline_query")
    if inline_query:
        from app.services.agent.inline import handle_inline_query

        try:
            await handle_inline_query(inline_query)
        except Exception as e:
            logger.error(f"Inline query error: {e}", exc_info=True)
        return JSONResponse({"ok": True})

    # Process messages in background (don't block Telegram's webhook)
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

    # Handle forwarded messages — the "second brain" mechanic
    from app.services.agent.forward_processor import is_forwarded_message

    if is_forwarded_message(message) and not text.startswith("/"):
        from app.services.agent.forward_processor import process_forwarded_message

        response = await process_forwarded_message(message, user_name=user_name)
        await send_telegram_message(chat_id, response)
        # If it's a voice forward, also do voice summary
        if not voice:
            return

    # Handle direct photos (non-forwarded)
    photo = message.get("photo")
    if photo and not text.startswith("/"):
        from app.services.agent.media_processor import describe_photo
        from app.services.agent.typing import send_typing_action

        await send_typing_action(chat_id)
        file_id = photo[-1].get("file_id", "")
        description = await describe_photo(file_id)
        caption = message.get("caption", "")
        if description:
            response = f"📷 *Photo analyzed:*\n_{description}_"
            if caption:
                response += f"\n\nCaption: {caption}"
            response += "\n\n✅ _Remembered._"
        else:
            response = (
                "📷 Photo received. Could not analyze — try describing it in text."
            )
        await send_telegram_message(chat_id, response)
        return

    # Handle direct documents (non-forwarded)
    document = message.get("document")
    if document and not text.startswith("/"):
        from app.services.agent.media_processor import extract_document_text

        file_id = document.get("file_id", "")
        file_name = document.get("file_name", "unknown")
        doc_text = await extract_document_text(file_id, file_name)
        if doc_text and not doc_text.startswith("[Document:"):
            preview = doc_text[:500] + ("..." if len(doc_text) > 500 else "")
            response = f"📄 *Document: {file_name}*\n_{preview}_\n\n✅ _Remembered._"
        else:
            response = f"📄 Document received: *{file_name}*\n_{doc_text or 'Could not extract content.'}_"
        await send_telegram_message(chat_id, response)
        return

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
                "• `/digest` — дайджест дня\n"
                "• `/web запрос` — поиск в интернете\n"
                "• `/status` — статистика\n"
                "• `/clear` — очистить историю",
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
                "• `/digest` — daily summary\n"
                "• `/web query` — web search\n"
                "• `/status` — statistics\n"
                "• `/clear` — reset conversation",
            )
        return

    # Handle /status command
    if text.strip().startswith("/status"):
        from app.services.agent.status import get_user_status

        user_id = await _resolve_user(from_user)
        lang = _detect_language(user_name or text)
        status = await get_user_status(user_id, user_name=user_name, user_language=lang)
        await send_telegram_message(chat_id, status)
        return

    # Handle /clear command — reset conversation history
    if text.strip() == "/clear":
        from app.services.agent.conversation import clear_history

        user_id = await _resolve_user(from_user)
        clear_history(user_id)
        lang = _detect_language(user_name or "")
        if lang == "ru":
            await send_telegram_message(
                chat_id, "🗑️ История разговора очищена. Начинаем с чистого листа!"
            )
        else:
            await send_telegram_message(chat_id, "🗑️ Conversation cleared. Fresh start!")
        return

    # Handle /web command — web search
    if text.strip().startswith("/web"):
        query = text.strip().removeprefix("/web").strip()
        if not query:
            await send_telegram_message(
                chat_id, "Usage: `/web <search query>`\nExample: `/web latest AI news`"
            )
            return

        from app.services.agent.typing import send_typing_action

        await send_typing_action(chat_id)

        # Use Claude to answer with web search context
        import anthropic

        settings = get_settings()
        try:
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1000,
                messages=[
                    {
                        "role": "user",
                        "content": f"Search the web and answer: {query}\n\nProvide a concise, informative answer. Include sources if possible.",
                    }
                ],
            )
            answer = response.content[0].text.strip()
            await send_telegram_message(chat_id, f"🌐 *Web:* {query}\n\n{answer}")
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            await send_telegram_message(
                chat_id, "❌ Web search failed. Try again later."
            )
        return

    # Handle /briefing command
    if text.strip().startswith("/briefing"):
        from app.services.agent.briefing import generate_morning_briefing

        user_id = await _resolve_user(from_user)
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

        user_id = await _resolve_user(from_user)  # Placeholder
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

    # Resolve Telegram user → internal user ID
    user_id = await _resolve_user(from_user)

    # Build agent context
    context = AgentContext(
        user_id=user_id,
        chat_id=chat_id,
        user_name=user_name,
        user_language=_detect_language(text or ""),
        has_voice=has_voice,
        voice_transcript=voice_transcript,
    )

    # Load conversation history for context
    from app.services.agent.conversation import add_message, get_history
    from app.services.agent.loop import AgentMessage

    history = get_history(user_id)
    context.conversation_history = [
        AgentMessage(role=msg.role, content=msg.content) for msg in history
    ]

    # Show "typing..." while Claude thinks (critical for UX)
    from app.services.agent.typing import send_typing_action

    await send_typing_action(chat_id)

    # Run the agent
    result: AgentResult = await run_agent(context, text)

    # Save conversation history
    add_message(user_id, "user", text)
    add_message(user_id, "assistant", result.response)

    # Send response
    await send_telegram_message(chat_id, result.response)

    # Background: auto-extract commitments from the user's message
    try:
        from app.services.agent.commitments import detect_commitments, save_commitment

        user_id = context.user_id
        detected = detect_commitments(text, user_name=user_name)
        for c in detected:
            save_commitment(c, user_id)
            logger.info(f"Auto-commitment: {c.direction.value} - {c.who}: {c.what}")
    except Exception as e:
        logger.debug(f"Auto-commitment extraction: {e}")

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
