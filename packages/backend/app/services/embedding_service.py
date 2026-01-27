import logging
from datetime import UTC, datetime
from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.message import TelegramMessage

logger = logging.getLogger(__name__)
settings = get_settings()


async def get_openai_client() -> AsyncOpenAI:
    """Get OpenAI client."""
    return AsyncOpenAI(api_key=settings.openai_api_key)


async def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a batch of texts."""
    if not texts:
        return []

    client = await get_openai_client()
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
        dimensions=settings.embedding_dimensions,
    )
    return [item.embedding for item in response.data]


async def embed_messages(
    db: AsyncSession, message_ids: list[UUID]
) -> int:
    """Generate embeddings for messages. Returns count of embedded messages."""
    if not message_ids:
        return 0

    # Fetch messages
    result = await db.execute(
        select(TelegramMessage).where(
            TelegramMessage.id.in_(message_ids),
            TelegramMessage.text.isnot(None),
            TelegramMessage.embedding.is_(None),
        )
    )
    messages = result.scalars().all()

    if not messages:
        return 0

    # Prepare texts for embedding
    texts = []
    msg_indices = []
    for i, msg in enumerate(messages):
        if msg.text and msg.text.strip():
            texts.append(msg.text[:8000])  # Truncate long messages
            msg_indices.append(i)

    if not texts:
        return 0

    # Batch embedding
    embedded_count = 0
    for batch_start in range(0, len(texts), settings.embedding_batch_size):
        batch_end = batch_start + settings.embedding_batch_size
        batch_texts = texts[batch_start:batch_end]
        batch_indices = msg_indices[batch_start:batch_end]

        try:
            embeddings = await generate_embeddings(batch_texts)
            for j, embedding in enumerate(embeddings):
                msg_idx = batch_indices[j]
                messages[msg_idx].embedding = embedding
                messages[msg_idx].embedded_at = datetime.now(UTC)
                embedded_count += 1
        except Exception as e:
            logger.error(f"Error generating embeddings: {e}")
            continue

    await db.flush()
    return embedded_count


async def embed_unembedded_messages(
    db: AsyncSession, user_id: UUID, limit: int = 1000
) -> int:
    """Find and embed messages without embeddings."""
    from app.models.chat import TelegramChat

    # Get messages without embeddings for this user
    result = await db.execute(
        select(TelegramMessage.id)
        .join(TelegramChat)
        .where(
            TelegramChat.user_id == user_id,
            TelegramMessage.text.isnot(None),
            TelegramMessage.embedding.is_(None),
        )
        .limit(limit)
    )
    message_ids = [row[0] for row in result.all()]

    return await embed_messages(db, message_ids)


async def generate_query_embedding(query: str) -> list[float]:
    """Generate embedding for a search query."""
    embeddings = await generate_embeddings([query])
    return embeddings[0] if embeddings else []
