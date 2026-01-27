import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import anthropic
from anthropic import APIError, APIConnectionError, RateLimitError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.chat import TelegramChat
from app.models.digest import DailyDigest
from app.models.message import TelegramMessage

logger = logging.getLogger(__name__)
settings = get_settings()

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY = 1.0  # seconds


async def generate_digest(
    db: AsyncSession,
    user_id: UUID,
    digest_date: date | None = None,
) -> DailyDigest:
    """Generate a daily digest for a user."""
    if digest_date is None:
        digest_date = (datetime.now(UTC) - timedelta(days=1)).date()

    # Check if digest already exists
    result = await db.execute(
        select(DailyDigest).where(
            DailyDigest.user_id == user_id,
            DailyDigest.digest_date == digest_date,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    # Get date range
    start_dt = datetime.combine(digest_date, datetime.min.time()).replace(tzinfo=UTC)
    end_dt = start_dt + timedelta(days=1)

    # Fetch messages for the day
    result = await db.execute(
        select(TelegramMessage, TelegramChat.title)
        .join(TelegramChat)
        .where(
            TelegramChat.user_id == user_id,
            TelegramMessage.sent_at >= start_dt,
            TelegramMessage.sent_at < end_dt,
        )
        .order_by(TelegramMessage.sent_at)
    )
    rows = result.all()

    if not rows:
        # No messages, create empty digest
        digest = DailyDigest(
            user_id=user_id,
            digest_date=digest_date,
            content="No messages to summarize for this day.",
            summary_stats={"total_messages": 0, "chats": []},
        )
        db.add(digest)
        await db.flush()
        return digest

    # Prepare data for LLM
    messages_by_chat: dict[str, list[str]] = {}
    for message, chat_title in rows:
        if chat_title not in messages_by_chat:
            messages_by_chat[chat_title] = []
        if message.text:
            sender = message.sender_name or ("You" if message.is_outgoing else "Unknown")
            messages_by_chat[chat_title].append(f"{sender}: {message.text[:500]}")

    # Build prompt
    chat_summaries = []
    for chat, msgs in messages_by_chat.items():
        chat_summaries.append(f"## {chat}\n" + "\n".join(msgs[:50]))  # Limit messages

    prompt = f"""Summarize the following Telegram messages from {digest_date.strftime('%B %d, %Y')}.

Create a concise daily digest that includes:
1. **Highlights**: Key topics or interesting conversations
2. **Action Items**: Any tasks, requests, or things that need follow-up
3. **Statistics**: Brief stats about message activity

Messages by chat:

{'---'.join(chat_summaries[:10])}

Keep the summary concise and actionable. Focus on what's most important."""

    # Call Claude with retry logic
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    content = None
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.messages.create(
                model=settings.digest_model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.content[0].text
            break
        except RateLimitError as e:
            last_error = e
            wait_time = BASE_DELAY * (2 ** attempt)
            logger.warning(f"Rate limited on digest generation, attempt {attempt + 1}/{MAX_RETRIES}, waiting {wait_time}s")
            await asyncio.sleep(wait_time)
        except APIConnectionError as e:
            last_error = e
            wait_time = BASE_DELAY * (2 ** attempt)
            logger.warning(f"API connection error on digest generation, attempt {attempt + 1}/{MAX_RETRIES}: {e}")
            await asyncio.sleep(wait_time)
        except APIError as e:
            last_error = e
            logger.error(f"Anthropic API error on digest generation: {e}")
            # Don't retry on non-recoverable API errors (4xx errors except rate limit)
            if e.status_code and 400 <= e.status_code < 500 and e.status_code != 429:
                break
            wait_time = BASE_DELAY * (2 ** attempt)
            await asyncio.sleep(wait_time)

    if content is None:
        logger.error(f"Failed to generate digest after {MAX_RETRIES} attempts: {last_error}")
        content = f"Failed to generate AI summary. Error: {str(last_error) if last_error else 'Unknown error'}"

    # Compute stats
    stats = {
        "total_messages": len(rows),
        "chats": list(messages_by_chat.keys()),
        "messages_per_chat": {k: len(v) for k, v in messages_by_chat.items()},
    }

    # Create digest
    digest = DailyDigest(
        user_id=user_id,
        digest_date=digest_date,
        content=content,
        summary_stats=stats,
    )
    db.add(digest)
    await db.flush()

    return digest


async def get_digest(
    db: AsyncSession,
    user_id: UUID,
    digest_date: date,
) -> DailyDigest | None:
    """Get a digest for a specific date."""
    result = await db.execute(
        select(DailyDigest).where(
            DailyDigest.user_id == user_id,
            DailyDigest.digest_date == digest_date,
        )
    )
    return result.scalar_one_or_none()


async def get_digests(
    db: AsyncSession,
    user_id: UUID,
    limit: int = 30,
) -> list[DailyDigest]:
    """Get recent digests for a user."""
    result = await db.execute(
        select(DailyDigest)
        .where(DailyDigest.user_id == user_id)
        .order_by(DailyDigest.digest_date.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
