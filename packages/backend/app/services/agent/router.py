"""Intent Router — classifies user messages and routes to the right agent.

Uses cheap model (Haiku) for instant classification. Routes to:
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

import anthropic

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class Intent(StrEnum):
    SEARCH = "search"
    VOICE_SUMMARY = "voice_summary"
    DIGEST = "digest"
    ACTION = "action"
    BUILD = "build"
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

# Model routing: cheap for classification, expensive for complex tasks
MODEL_MAP: dict[Intent, str] = {
    Intent.SEARCH: "claude-haiku-4-5-20251001",
    Intent.VOICE_SUMMARY: "claude-haiku-4-5-20251001",
    Intent.DIGEST: "claude-sonnet-4-6-20250514",
    Intent.ACTION: "claude-sonnet-4-6-20250514",
    Intent.BUILD: "claude-opus-4-6-20250514",
    Intent.COACH: "claude-sonnet-4-6-20250514",
    Intent.CHAT: "claude-haiku-4-5-20251001",
}


async def classify_intent(message: str, has_voice: bool = False) -> Intent:
    """Classify a user message into an intent using Haiku (fast + cheap)."""
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

    # LLM classification for truly ambiguous messages
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[
                {
                    "role": "user",
                    "content": CLASSIFICATION_PROMPT.format(message=message[:500]),
                }
            ],
        )
        intent_text = response.content[0].text.strip().lower()

        for intent in Intent:
            if intent.value in intent_text:
                return intent

        return Intent.CHAT
    except Exception as e:
        logger.warning(f"Intent classification failed, defaulting to chat: {e}")
        return Intent.CHAT


def get_model_for_intent(intent: Intent) -> str:
    """Get the appropriate model for the classified intent."""
    return MODEL_MAP.get(intent, MODEL_MAP[Intent.CHAT])
