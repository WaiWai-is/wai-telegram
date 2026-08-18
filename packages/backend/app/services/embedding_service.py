import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import asyncio

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.message import TelegramMessage

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass(frozen=True)
class PreparedContentChunk:
    text: str
    embedding: list[float]


@dataclass(frozen=True)
class PreparedMediaContentIndex:
    message_text: str
    message_embedding: list[float]
    chunks: list[PreparedContentChunk]


_client: AsyncOpenAI | None = None
_client_lock = asyncio.Lock()


async def get_openai_client() -> AsyncOpenAI:
    """Return the shared OpenAI client, building it once.

    A fresh AsyncOpenAI per call meant a fresh TCP connection and TLS handshake
    for every embedding, and the discarded clients were never closed. Query
    embedding dominated search latency because of it - about two seconds against
    the quarter second the same request takes over a warm connection.
    """
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def close_openai_client() -> None:
    """Release the shared client, for shutdown and for tests."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None


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


async def prepare_media_content_index(
    *,
    caption: str | None,
    summary: str,
    content_text: str | None,
) -> PreparedMediaContentIndex:
    """Build a complete media index or fail before mutating database state."""
    from app.services.media_content_service import chunk_text

    message_text = "\n\n".join(
        part.strip()
        for part in (caption, summary)
        if isinstance(part, str) and part.strip()
    )
    if not message_text:
        raise RuntimeError("Media summary is required for indexing")

    chunks = chunk_text(
        content_text.strip() if content_text else "",
        max_chars=settings.media_embedding_chunk_chars,
        overlap_chars=settings.media_embedding_chunk_overlap_chars,
    )
    inputs = [message_text, *chunks]
    embeddings: list[list[float]] = []
    for start in range(0, len(inputs), settings.embedding_batch_size):
        batch = inputs[start : start + settings.embedding_batch_size]
        batch_embeddings = await generate_embeddings(batch)
        if len(batch_embeddings) != len(batch):
            raise RuntimeError(
                "OpenAI returned "
                f"{len(batch_embeddings)} embeddings; expected {len(batch)} embeddings"
            )
        embeddings.extend(batch_embeddings)

    return PreparedMediaContentIndex(
        message_text=message_text,
        message_embedding=embeddings[0],
        chunks=[
            PreparedContentChunk(text=text, embedding=embedding)
            for text, embedding in zip(chunks, embeddings[1:], strict=True)
        ],
    )


async def embed_messages(db: AsyncSession, message_ids: list[UUID]) -> int:
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
