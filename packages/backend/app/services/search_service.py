import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.chat import TelegramChat
from app.models.message import TelegramMessage
from app.schemas.search import SearchRequest, SearchResponse, SearchResultItem
from app.services.embedding_service import generate_query_embedding

logger = logging.getLogger(__name__)
settings = get_settings()


async def semantic_search(
    db: AsyncSession,
    user_id: UUID,
    request: SearchRequest,
) -> SearchResponse:
    """Perform semantic search across user's messages."""
    # Generate query embedding
    query_embedding = await generate_query_embedding(request.query)
    if not query_embedding:
        return SearchResponse(results=[], query=request.query, total=0)

    dimensions = settings.embedding_dimensions

    # Build query dynamically to avoid asyncpg AmbiguousParameterError
    # when optional filters are None.
    where_clauses = [
        "c.user_id = :user_id",
        "m.embedding IS NOT NULL",
    ]
    params: dict = {
        "user_id": str(user_id),
        "limit": request.limit,
    }

    # Format embedding as pgvector string literal for parameterized query
    embedding_literal = "[" + ",".join(str(x) for x in query_embedding) + "]"
    params["embedding"] = embedding_literal

    if request.chat_ids:
        where_clauses.append("m.chat_id = ANY(:chat_ids)")
        params["chat_ids"] = [str(cid) for cid in request.chat_ids]

    if request.date_from:
        where_clauses.append("m.sent_at >= :date_from")
        params["date_from"] = request.date_from

    if request.date_to:
        where_clauses.append("m.sent_at <= :date_to")
        params["date_to"] = request.date_to

    where_sql = " AND ".join(where_clauses)

    sql = text(f"""
        SELECT
            m.id,
            m.chat_id,
            c.title as chat_title,
            c.username as chat_username,
            m.telegram_message_id,
            m.text,
            m.sender_name,
            m.is_outgoing,
            m.sent_at,
            1 - (m.embedding <=> cast(:embedding as vector({dimensions}))) as similarity,
            m.has_media,
            m.media_type,
            m.transcribed_at
        FROM telegram_messages m
        JOIN telegram_chats c ON m.chat_id = c.id
        WHERE {where_sql}
        ORDER BY similarity DESC
        LIMIT :limit
    """)

    result = await db.execute(sql, params)
    rows = result.fetchall()

    results = [
        SearchResultItem(
            id=row.id,
            chat_id=row.chat_id,
            chat_title=row.chat_title,
            chat_username=row.chat_username,
            telegram_message_id=row.telegram_message_id,
            text=row.text,
            sender_name=row.sender_name,
            is_outgoing=row.is_outgoing,
            sent_at=row.sent_at,
            similarity=row.similarity,
            has_media=row.has_media,
            media_type=row.media_type,
            transcribed_at=row.transcribed_at,
        )
        for row in rows
    ]

    return SearchResponse(
        results=results,
        query=request.query,
        total=len(results),
    )


async def get_recent_messages(
    db: AsyncSession,
    user_id: UUID,
    chat_id: UUID | None = None,
    hours: int = 24,
    limit: int = 100,
) -> list[TelegramMessage]:
    """Get recent messages for a user."""
    from datetime import UTC, timedelta

    cutoff = datetime.now(UTC) - timedelta(hours=hours)

    query = (
        select(TelegramMessage)
        .join(TelegramChat)
        .where(
            TelegramChat.user_id == user_id,
            TelegramMessage.sent_at >= cutoff,
        )
    )

    if chat_id:
        query = query.where(TelegramMessage.chat_id == chat_id)

    query = query.order_by(TelegramMessage.sent_at.desc()).limit(limit)

    result = await db.execute(query)
    return list(result.scalars().all())
