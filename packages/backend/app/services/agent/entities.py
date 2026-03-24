"""Entity Extraction — auto-extract people, topics, decisions from messages.

Inspired by wai-computer's entity system but lightweight for Telegram.
Two modes:
1. Fast pattern-based extraction (no LLM, instant)
2. LLM-powered deep extraction (Claude Haiku, ~1s)

Entity types: person, topic, decision, action_item, date, amount
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class EntityType(StrEnum):
    PERSON = "person"
    TOPIC = "topic"
    DECISION = "decision"
    ACTION_ITEM = "action_item"
    DATE = "date"
    AMOUNT = "amount"
    LOCATION = "location"


@dataclass
class Entity:
    id: UUID = field(default_factory=uuid4)
    type: EntityType = EntityType.TOPIC
    name: str = ""
    context: str = ""  # Surrounding text
    confidence: float = 1.0
    source_chat: str | None = None
    extracted_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# Patterns for fast extraction
PERSON_PATTERNS = [
    # @mentions
    r"@(\w{3,32})",
    # "Alex said", "told Maria", common name patterns
    r"(?:with|from|told|asked|called|met|emailed)\s+([A-Z][a-z]{2,15}(?:\s+[A-Z][a-z]{2,15})?)",
    # Russian names
    r"(?:с|от|у|для|сказал[а]?|спросил[а]?|встретил[а]?)\s+([А-ЯЁ][а-яё]{2,15}(?:\s+[А-ЯЁ][а-яё]{2,15})?)",
]

AMOUNT_PATTERNS = [
    r"\$\s*(\d[\d,]*(?:\.\d{2})?)\s*(?:k|K|M|B)?",
    r"(\d[\d,]*(?:\.\d{2})?)\s*(?:dollars|USD|EUR|руб|₽|€)",
    r"(\d[\d,.]+)\s*(?:k|K|тыс|млн|M)\b",
]

DATE_PATTERNS = [
    r"(?:on|at|by|before|after|since|until|от|до|с|к|после|перед)\s+"
    r"(\d{1,2}[/.\-]\d{1,2}(?:[/.\-]\d{2,4})?)",
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2}(?:,?\s*\d{4})?)",
    r"(\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря))",
]

DECISION_MARKERS = [
    r"(?:we decided|agreed|the plan is|going with|решили|договорились|план такой)\s+(.{10,150})",
    r"(?:decision|решение):\s*(.{10,150})",
    r"(?:final answer|итого|в итоге|bottom line):\s*(.{10,150})",
]


def extract_entities_fast(text: str) -> list[Entity]:
    """Fast pattern-based entity extraction. No LLM call. Instant."""
    entities: list[Entity] = []

    # Extract people
    for pattern in PERSON_PATTERNS:
        for match in re.finditer(pattern, text):
            name = match.group(1).strip()
            if len(name) >= 2 and name not in {"The", "This", "That", "Это", "Вот"}:
                entities.append(
                    Entity(
                        type=EntityType.PERSON,
                        name=name,
                        context=text[max(0, match.start() - 20) : match.end() + 20],
                        confidence=0.7,
                    )
                )

    # Extract amounts
    for pattern in AMOUNT_PATTERNS:
        for match in re.finditer(pattern, text):
            entities.append(
                Entity(
                    type=EntityType.AMOUNT,
                    name=match.group(0).strip(),
                    context=text[max(0, match.start() - 20) : match.end() + 20],
                    confidence=0.9,
                )
            )

    # Extract dates
    for pattern in DATE_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            entities.append(
                Entity(
                    type=EntityType.DATE,
                    name=match.group(1).strip(),
                    context=text[max(0, match.start() - 20) : match.end() + 20],
                    confidence=0.8,
                )
            )

    # Extract decisions
    for pattern in DECISION_MARKERS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            entities.append(
                Entity(
                    type=EntityType.DECISION,
                    name=match.group(1).strip()[:200],
                    context=text[max(0, match.start() - 20) : match.end() + 20],
                    confidence=0.8,
                )
            )

    # Deduplicate by name+type
    seen = set()
    unique = []
    for e in entities:
        key = (e.type, e.name.lower())
        if key not in seen:
            seen.add(key)
            unique.append(e)

    return unique


async def extract_entities_llm(text: str) -> list[Entity]:
    """LLM-powered entity extraction using Claude Haiku. More accurate but costs ~$0.001."""
    import anthropic

    from app.core.config import get_settings

    settings = get_settings()

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": f"""Extract entities from this message. Return one entity per line in format:
TYPE|NAME|CONTEXT
Types: person, topic, decision, action_item, amount, location
Only include clearly mentioned entities. Be concise.

Message: {text[:1000]}""",
                }
            ],
        )

        entities = []
        for line in response.content[0].text.strip().split("\n"):
            parts = line.split("|", 2)
            if len(parts) >= 2:
                entity_type = parts[0].strip().lower()
                name = parts[1].strip()
                context = parts[2].strip() if len(parts) > 2 else ""

                if entity_type in {e.value for e in EntityType} and name:
                    entities.append(
                        Entity(
                            type=EntityType(entity_type),
                            name=name[:200],
                            context=context[:200],
                            confidence=0.9,
                        )
                    )

        return entities
    except Exception as e:
        logger.warning(f"LLM entity extraction failed, falling back to fast: {e}")
        return extract_entities_fast(text)


def format_entities_for_display(entities: list[Entity]) -> str:
    """Format entities as a readable string."""
    if not entities:
        return "No entities detected."

    by_type: dict[EntityType, list[Entity]] = {}
    for e in entities:
        by_type.setdefault(e.type, []).append(e)

    icons = {
        EntityType.PERSON: "👤",
        EntityType.TOPIC: "📌",
        EntityType.DECISION: "✅",
        EntityType.ACTION_ITEM: "📋",
        EntityType.DATE: "📅",
        EntityType.AMOUNT: "💰",
        EntityType.LOCATION: "📍",
    }

    lines = []
    for entity_type, type_entities in by_type.items():
        icon = icons.get(entity_type, "•")
        type_name = entity_type.value.replace("_", " ").title()
        lines.append(f"{icon} *{type_name}s:*")
        for e in type_entities:
            lines.append(f"  • {e.name}")

    return "\n".join(lines)
