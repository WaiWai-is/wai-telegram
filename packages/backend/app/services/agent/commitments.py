"""Commitment Tracking — never forget a promise.

Detects commitments in conversations:
- "I'll send..." → user promised something
- "He said he'd..." → someone promised user
- "Let's meet on..." → mutual commitment
- "Напишу до пятницы" → Russian commitment detection

Tracks bi-directionally:
1. What YOU promised others
2. What OTHERS promised you

Stores in-memory for now (DB migration in next cycle).
Proactive reminders when deadlines approach.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class CommitmentDirection(StrEnum):
    I_PROMISED = "i_promised"
    THEY_PROMISED = "they_promised"
    MUTUAL = "mutual"


class CommitmentStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


@dataclass
class Commitment:
    id: UUID = field(default_factory=uuid4)
    user_id: UUID | None = None
    who: str = ""  # Person involved
    what: str = ""  # What was promised
    direction: CommitmentDirection = CommitmentDirection.THEY_PROMISED
    deadline: str | None = None  # Free-form deadline text
    status: CommitmentStatus = CommitmentStatus.OPEN
    source_chat: str | None = None  # Chat where it was detected
    source_message: str | None = None  # Original message snippet
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


# In-memory store (replaced with DB in next cycle)
_commitments: list[Commitment] = []


# Patterns for detecting commitments in text
I_PROMISED_PATTERNS = [
    # English
    r"(?:i'll|i will|i'm going to|let me|i can|i should|i need to|i have to)\s+(.{10,80})",
    r"(?:will do|on it|i'll handle|consider it done|leave it to me)",
    # Russian
    r"(?:я отправлю|я пришлю|я сделаю|я напишу|я позвоню|я подготовлю)\s*(.*)",
    r"(?:сделаю|напишу|отправлю|пришлю|позвоню|подготовлю)\s+(.{5,80})",
    r"(?:обещаю|договорились|беру на себя)",
]

THEY_PROMISED_PATTERNS = [
    # English
    r"(?:he'll|she'll|they'll|he will|she will|they will)\s+(.{10,80})",
    r"(\w+)\s+(?:said (?:he|she|they)'d|promised to|agreed to|committed to)\s+(.{10,80})",
    r"(\w+)\s+(?:will send|will do|will handle|will prepare|will call)\s*(.*)",
    # Russian
    r"(\w+)\s+(?:обещал[аи]?|сказал[аи]?\s+что)\s+(.{5,80})",
    r"(\w+)\s+(?:пришлёт|отправит|сделает|напишет|позвонит|подготовит)\s*(.*)",
]

DEADLINE_PATTERNS = [
    # English
    r"(?:by|before|until|no later than)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
    r"(?:by|before|until)\s+(tomorrow|next week|end of (?:day|week|month))",
    r"(?:by|before|until|no later than)\s+(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?)",
    # Russian
    r"(?:до|к|не позднее)\s+(понедельника|вторника|среды|четверга|пятницы|субботы|воскресенья)",
    r"(?:до|к)\s+(завтра|следующей недели|конца (?:дня|недели|месяца))",
    r"(?:до|к)\s+(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?)",
]


def detect_commitments(text: str, user_name: str | None = None) -> list[Commitment]:
    """Detect commitments in a text message.

    Returns a list of detected commitments with direction and deadline.
    """
    commitments = []
    lower = text.lower()

    # Detect "I promised" patterns
    for pattern in I_PROMISED_PATTERNS:
        match = re.search(pattern, lower, re.IGNORECASE)
        if match:
            what = (
                match.group(1)
                if match.lastindex and match.lastindex >= 1
                else match.group(0)
            )
            deadline = _extract_deadline(text)
            commitments.append(
                Commitment(
                    who=user_name or "me",
                    what=what.strip()[:200],
                    direction=CommitmentDirection.I_PROMISED,
                    deadline=deadline,
                    source_message=text[:300],
                )
            )
            break  # One commitment per pattern group

    # Detect "They promised" patterns
    for pattern in THEY_PROMISED_PATTERNS:
        match = re.search(pattern, lower, re.IGNORECASE)
        if match:
            who = (
                match.group(1)
                if match.lastindex and match.lastindex >= 1
                else "someone"
            )
            what = (
                match.group(2)
                if match.lastindex and match.lastindex >= 2
                else match.group(0)
            )
            deadline = _extract_deadline(text)
            commitments.append(
                Commitment(
                    who=who.strip().capitalize(),
                    what=what.strip()[:200],
                    direction=CommitmentDirection.THEY_PROMISED,
                    deadline=deadline,
                    source_message=text[:300],
                )
            )
            break

    return commitments


def _extract_deadline(text: str) -> str | None:
    """Extract deadline from text if present."""
    for pattern in DEADLINE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def save_commitment(commitment: Commitment, user_id: UUID) -> Commitment:
    """Save a commitment to the store."""
    commitment.user_id = user_id
    _commitments.append(commitment)
    logger.info(
        f"Commitment saved: {commitment.direction.value} - "
        f"{commitment.who}: {commitment.what} (deadline: {commitment.deadline})"
    )
    return commitment


def get_user_commitments(
    user_id: UUID,
    direction: CommitmentDirection | None = None,
    status: CommitmentStatus = CommitmentStatus.OPEN,
) -> list[Commitment]:
    """Get all commitments for a user, optionally filtered."""
    results = [c for c in _commitments if c.user_id == user_id and c.status == status]
    if direction:
        results = [c for c in results if c.direction == direction]
    return sorted(results, key=lambda c: c.created_at, reverse=True)


def complete_commitment(commitment_id: UUID) -> Commitment | None:
    """Mark a commitment as completed."""
    for c in _commitments:
        if c.id == commitment_id:
            c.status = CommitmentStatus.COMPLETED
            c.completed_at = datetime.now(UTC)
            return c
    return None


async def save_commitment_db(commitment: Commitment, user_id: UUID) -> None:
    """Persist a commitment to PostgreSQL (non-blocking)."""
    try:
        from app.core.database import async_session_factory
        from app.models.commitment import Commitment as CommitmentModel

        async with async_session_factory() as db:
            db_commitment = CommitmentModel(
                user_id=user_id,
                who=commitment.who,
                what=commitment.what,
                direction=commitment.direction.value,
                deadline=commitment.deadline,
                status=commitment.status.value,
                source_chat=commitment.source_chat,
                source_message=commitment.source_message,
            )
            db.add(db_commitment)
            await db.commit()
            logger.info(
                f"Commitment persisted to DB: {commitment.who}: {commitment.what}"
            )
    except Exception as e:
        logger.debug(f"DB persistence skipped (in-memory only): {e}")


async def get_user_commitments_db(
    user_id: UUID,
    direction: CommitmentDirection | None = None,
    status: CommitmentStatus = CommitmentStatus.OPEN,
) -> list[Commitment]:
    """Get commitments from DB, falling back to in-memory."""
    try:
        from sqlalchemy import select

        from app.core.database import async_session_factory
        from app.models.commitment import Commitment as CommitmentModel

        async with async_session_factory() as db:
            query = select(CommitmentModel).where(
                CommitmentModel.user_id == user_id,
                CommitmentModel.status == status.value,
            )
            if direction:
                query = query.where(CommitmentModel.direction == direction.value)
            query = query.order_by(CommitmentModel.created_at.desc())
            result = await db.execute(query)
            rows = result.scalars().all()

            return [
                Commitment(
                    id=row.id,
                    user_id=row.user_id,
                    who=row.who,
                    what=row.what,
                    direction=CommitmentDirection(row.direction),
                    deadline=row.deadline,
                    status=CommitmentStatus(row.status),
                    source_chat=row.source_chat,
                    source_message=row.source_message,
                    created_at=row.created_at,
                    completed_at=row.completed_at,
                )
                for row in rows
            ]
    except Exception as e:
        logger.debug(f"DB query failed, using in-memory: {e}")
        return get_user_commitments(user_id, direction, status)


def format_commitments_for_display(commitments: list[Commitment]) -> str:
    """Format commitments as a readable string for Telegram."""
    if not commitments:
        return "No open commitments found."

    lines = []
    i_promised = [
        c for c in commitments if c.direction == CommitmentDirection.I_PROMISED
    ]
    they_promised = [
        c for c in commitments if c.direction == CommitmentDirection.THEY_PROMISED
    ]

    if i_promised:
        lines.append("📤 *What you promised:*")
        for c in i_promised:
            deadline_text = f" (by {c.deadline})" if c.deadline else ""
            lines.append(f"  • {c.what}{deadline_text}")

    if they_promised:
        lines.append("\n📥 *What others promised you:*")
        for c in they_promised:
            deadline_text = f" (by {c.deadline})" if c.deadline else ""
            lines.append(f"  • {c.who}: {c.what}{deadline_text}")

    return "\n".join(lines)
