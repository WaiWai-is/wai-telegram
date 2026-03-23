import logging
import re
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


class SearchServiceError(RuntimeError):
    """Raised when search cannot be completed by any available strategy."""


def _empty_response(query: str) -> SearchResponse:
    return SearchResponse(results=[], query=query, total=0)


def _search_log_extra(
    user_id: UUID,
    request: SearchRequest,
    **extra: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "user_id": str(user_id),
        "query_length": len(request.query.strip()),
        "chat_filter_count": len(request.chat_ids or []),
        "has_date_from": request.date_from is not None,
        "has_date_to": request.date_to is not None,
        "limit": request.limit,
    }
    payload.update(extra)
    return payload


def _base_where_clauses(
    user_id: UUID,
    request: SearchRequest,
) -> tuple[list[str], dict[str, object]]:
    where_clauses = ["c.user_id = :user_id"]
    params: dict[str, object] = {
        "user_id": str(user_id),
        "limit": request.limit,
    }

    if request.chat_ids:
        where_clauses.append("m.chat_id = ANY(:chat_ids)")
        params["chat_ids"] = [str(cid) for cid in request.chat_ids]

    if request.date_from:
        where_clauses.append("m.sent_at >= :date_from")
        params["date_from"] = request.date_from

    if request.date_to:
        where_clauses.append("m.sent_at <= :date_to")
        params["date_to"] = request.date_to

    return where_clauses, params


def _rows_to_response(rows: list, query: str) -> SearchResponse:
    results = [
        SearchResultItem(
            id=row.id,
            chat_id=row.chat_id,
            chat_title=row.chat_title,
            chat_type=row.chat_type,
            chat_telegram_id=row.chat_telegram_id,
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
        query=query,
        total=len(results),
    )


def _like_pattern(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


def _query_tokens(query: str) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for token in re.findall(r"\w+", query, flags=re.UNICODE):
        normalized = token.strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        tokens.append(normalized)
        if len(tokens) >= 8:
            break
    return tokens


async def _keyword_search(
    db: AsyncSession,
    user_id: UUID,
    request: SearchRequest,
) -> SearchResponse:
    """Fallback search that matches query terms directly in message text and metadata."""
    normalized_query = request.query.strip()
    if not normalized_query:
        return _empty_response(request.query)

    where_clauses, params = _base_where_clauses(user_id, request)
    where_clauses.append("m.text IS NOT NULL")

    searchable_text = (
        "concat_ws(' ', coalesce(m.text, ''), coalesce(m.sender_name, ''), "
        "coalesce(c.title, ''), coalesce(c.username, ''))"
    )
    match_clauses = [f"{searchable_text} ILIKE :query_pattern ESCAPE '\\\\'"]
    score_terms = [f"CASE WHEN {searchable_text} ILIKE :query_pattern ESCAPE '\\\\' THEN 2 ELSE 0 END"]
    params["query_pattern"] = _like_pattern(normalized_query)

    for idx, token in enumerate(_query_tokens(normalized_query)):
        param_name = f"token_{idx}"
        match_clauses.append(f"{searchable_text} ILIKE :{param_name} ESCAPE '\\\\'")
        score_terms.append(
            f"CASE WHEN {searchable_text} ILIKE :{param_name} ESCAPE '\\\\' THEN 1 ELSE 0 END"
        )
        params[param_name] = _like_pattern(token)

    where_clauses.append("(" + " OR ".join(match_clauses) + ")")
    where_sql = " AND ".join(where_clauses)
    score_sql = f"(({' + '.join(score_terms)})::float / {len(score_terms) + 1})"

    sql = text(f"""
        SELECT
            m.id,
            m.chat_id,
            c.title as chat_title,
            c.chat_type as chat_type,
            c.telegram_chat_id as chat_telegram_id,
            c.username as chat_username,
            m.telegram_message_id,
            m.text,
            m.sender_name,
            m.is_outgoing,
            m.sent_at,
            {score_sql} as similarity,
            m.has_media,
            m.media_type,
            m.transcribed_at
        FROM telegram_messages m
        JOIN telegram_chats c ON m.chat_id = c.id
        WHERE {where_sql}
        ORDER BY similarity DESC, m.sent_at DESC
        LIMIT :limit
    """)

    result = await db.execute(sql, params)
    return _rows_to_response(result.fetchall(), request.query)


async def semantic_search(
    db: AsyncSession,
    user_id: UUID,
    request: SearchRequest,
) -> SearchResponse:
    """Perform semantic search across user's messages."""
    normalized_query = request.query.strip()
    if not normalized_query:
        logger.info(
            "Search skipped for blank query",
            extra=_search_log_extra(user_id, request, mode="blank_query"),
        )
        return _empty_response(request.query)

    # Generate query embedding
    try:
        query_embedding = await generate_query_embedding(normalized_query)
    except Exception:
        logger.exception(
            "Semantic search embedding generation failed; falling back to keyword search",
            extra=_search_log_extra(user_id, request, mode="embedding_failure"),
        )
        try:
            response = await _keyword_search(db, user_id, request)
            logger.info(
                "Keyword search fallback succeeded after embedding failure",
                extra=_search_log_extra(
                    user_id,
                    request,
                    mode="keyword_fallback_after_embedding_failure",
                    results=response.total,
                ),
            )
            return response
        except Exception as fallback_exc:
            logger.exception(
                "Keyword search fallback failed after embedding failure",
                extra=_search_log_extra(
                    user_id,
                    request,
                    mode="keyword_fallback_failure_after_embedding_failure",
                ),
            )
            raise SearchServiceError("Search is temporarily unavailable") from fallback_exc

    if not query_embedding:
        logger.info(
            "Search returned empty embedding result",
            extra=_search_log_extra(user_id, request, mode="empty_embedding"),
        )
        return _empty_response(request.query)

    dimensions = settings.embedding_dimensions

    # Build query dynamically to avoid asyncpg AmbiguousParameterError
    # when optional filters are None.
    where_clauses, params = _base_where_clauses(user_id, request)
    where_clauses.append("m.embedding IS NOT NULL")

    # Format embedding as pgvector string literal for parameterized query
    embedding_literal = "[" + ",".join(str(x) for x in query_embedding) + "]"
    params["embedding"] = embedding_literal

    where_sql = " AND ".join(where_clauses)

    sql = text(f"""
        SELECT
            m.id,
            m.chat_id,
            c.title as chat_title,
            c.chat_type as chat_type,
            c.telegram_chat_id as chat_telegram_id,
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

    try:
        result = await db.execute(sql, params)
        return _rows_to_response(result.fetchall(), request.query)
    except Exception:
        logger.exception(
            "Semantic vector search failed; falling back to keyword search",
            extra=_search_log_extra(user_id, request, mode="vector_query_failure"),
        )
        try:
            response = await _keyword_search(db, user_id, request)
            logger.info(
                "Keyword search fallback succeeded after vector search failure",
                extra=_search_log_extra(
                    user_id,
                    request,
                    mode="keyword_fallback_after_vector_failure",
                    results=response.total,
                ),
            )
            return response
        except Exception as fallback_exc:
            logger.exception(
                "Keyword search fallback failed after vector search failure",
                extra=_search_log_extra(
                    user_id,
                    request,
                    mode="keyword_fallback_failure_after_vector_failure",
                ),
            )
            raise SearchServiceError("Search is temporarily unavailable") from fallback_exc


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
