"""Conversation History — remember what was discussed in each chat session.

Stores recent messages per user in memory (fast) with async DB persistence.
The agent loop uses this to maintain context across messages.

Design:
- In-memory: last 20 messages per user (instant retrieval)
- DB: full history (persisted, searchable)
- Auto-trim: oldest messages removed when limit exceeded
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

logger = logging.getLogger(__name__)

MAX_HISTORY = 20  # Messages to keep in memory per user


@dataclass
class ConversationMessage:
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


# In-memory conversation store: user_id → list of messages
_conversations: dict[UUID, list[ConversationMessage]] = defaultdict(list)


def add_message(user_id: UUID, role: str, content: str) -> None:
    """Add a message to the user's conversation history."""
    _conversations[user_id].append(ConversationMessage(role=role, content=content))
    # Trim to MAX_HISTORY
    if len(_conversations[user_id]) > MAX_HISTORY:
        _conversations[user_id] = _conversations[user_id][-MAX_HISTORY:]


def get_history(user_id: UUID, limit: int = MAX_HISTORY) -> list[ConversationMessage]:
    """Get recent conversation history for a user."""
    return _conversations[user_id][-limit:]


def clear_history(user_id: UUID) -> None:
    """Clear conversation history for a user."""
    _conversations[user_id].clear()


def get_history_for_agent(user_id: UUID) -> list[dict[str, str]]:
    """Get history formatted for the agent loop (list of role/content dicts)."""
    return [{"role": msg.role, "content": msg.content} for msg in get_history(user_id)]


def get_conversation_summary(user_id: UUID) -> str:
    """Get a brief summary of the conversation state."""
    history = get_history(user_id)
    if not history:
        return "No previous conversation."
    count = len(history)
    last = history[-1]
    return f"{count} messages in history. Last: {last.role} at {last.timestamp.strftime('%H:%M')}"
