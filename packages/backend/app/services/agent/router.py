"""Intent Router — classifies user messages and routes to the right agent.

Uses the shared generation model for ambiguous classification. Routes to:
- search: find information in user's message history
- voice_summary: summarize a forwarded voice message
- digest: generate or fetch daily digest
- action: send email, create event, etc.
- build: create/deploy a site, bot, or app
- coach: teach user about AI prompting
- chat: general conversation with context
"""

import logging
from enum import StrEnum

from app.core.config import get_settings
from app.services.generation_service import generate_text

logger = logging.getLogger(__name__)
settings = get_settings()


class Intent(StrEnum):
    SEARCH = "search"
    VOICE_SUMMARY = "voice_summary"
    DIGEST = "digest"
    ACTION = "action"
    BUILD = "build"
    EDIT = "edit"
    COACH = "coach"
    CHAT = "chat"


CLASSIFICATION_PROMPT = """Classify the user's message into exactly ONE intent. Respond with ONLY the intent name, nothing else.

Intents:
- search: user wants to find something in their past messages/conversations ("what did X say about Y?", "find the link about Z")
- voice_summary: user forwarded a voice message and wants a summary
- digest: user wants a daily/weekly summary of their activity
- action: user wants to perform an action (send email, create calendar event, manage contacts)
- build: user wants to create/deploy something (website, bot, app, landing page)
- coach: user wants to learn about AI, prompting, or tools
- chat: general conversation, questions, brainstorming

User message: {message}
"""

# All runtime generation is intentionally pinned to one reviewed model.
MODEL_MAP: dict[Intent, str] = {intent: settings.generation_model for intent in Intent}


async def classify_intent(message: str, has_voice: bool = False) -> Intent:
    """Classify a user message into an intent using the shared fast profile."""
    if has_voice:
        return Intent.VOICE_SUMMARY

    # Quick pattern matching for common commands (skip LLM call — saves ~1s)
    lower = message.lower().strip()

    # Slash commands
    if lower.startswith(("/search", "/find", "/найди", "/поиск")):
        return Intent.SEARCH
    if lower.startswith(("/digest", "/дайджест", "/summary")):
        return Intent.DIGEST
    if lower.startswith(("/build", "/deploy", "/создай сайт", "/сделай")):
        return Intent.BUILD
    if lower.startswith(("/coach", "/teach", "/научи", "/промпт")):
        return Intent.COACH
    if lower.startswith(("/send", "/email", "/calendar", "/отправь", "/письмо")):
        return Intent.ACTION

    # Natural language patterns (skip LLM for obvious intents)
    search_keywords = [
        "search for",
        "find ",
        "what did",
        "when did",
        "who said",
        "найди",
        "поищи",
        "что говорил",
        "что обсуждали",
        "когда",
        "where is",
        "show me",
        "look for",
        "покажи",
        "где ",
    ]
    if any(lower.startswith(kw) or f" {kw}" in lower for kw in search_keywords):
        return Intent.SEARCH

    digest_keywords = [
        "digest",
        "summary of",
        "what happened",
        "дайджест",
        "что было",
        "итоги",
    ]
    if any(kw in lower for kw in digest_keywords):
        return Intent.DIGEST

    build_keywords = [
        "build ",
        "create ",
        "deploy ",
        "make a site",
        "make a bot",
        "построй",
        "создай",
        "задеплой",
        "сделай сайт",
        "сделай бот",
    ]
    if any(kw in lower for kw in build_keywords):
        return Intent.BUILD

    edit_keywords = [
        "change ",
        "modify ",
        "update ",
        "add ",
        "remove ",
        "make it ",
        "make the ",
        "replace ",
        "fix the ",
        "измени",
        "поменяй",
        "добавь",
        "убери",
        "сделай ",
        "замени",
        "поправь",
        "обнови",
        "darker",
        "lighter",
        "bigger",
        "smaller",
        "темнее",
        "светлее",
        "крупнее",
        "меньше",
    ]
    if any(lower.startswith(kw) or kw in lower for kw in edit_keywords):
        return Intent.EDIT

    action_keywords = [
        "send email",
        "send a message",
        "create event",
        "schedule",
        "отправь письмо",
        "отправь сообщение",
        "создай событие",
        "запланируй",
    ]
    if any(kw in lower for kw in action_keywords):
        return Intent.ACTION

    commitment_keywords = [
        "what did i promise",
        "what do i owe",
        "my commitments",
        "что я обещал",
        "мои обязательства",
        "что должен",
        "what did they promise",
        "who owes me",
    ]
    if any(kw in lower for kw in commitment_keywords):
        return Intent.SEARCH  # Route to search with commitment context

    # Model classification for truly ambiguous messages. Invalid provider output
    # is surfaced instead of silently changing the route to chat.
    intent_text = (
        await generate_text(
            CLASSIFICATION_PROMPT.format(message=message[:500]),
            max_output_tokens=20,
        )
    ).lower()
    try:
        return Intent(intent_text)
    except ValueError as exc:
        raise ValueError(f"Invalid intent classification: {intent_text!r}") from exc


def get_model_for_intent(intent: Intent) -> str:
    """Get the appropriate model for the classified intent."""
    return MODEL_MAP[intent]
