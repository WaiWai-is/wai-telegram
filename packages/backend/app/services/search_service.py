import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.cursor import CursorError, decode_cursor, encode_cursor
from app.models.chat import ChatType, TelegramChat
from app.models.message import TelegramMessage
from app.schemas.search import SearchRequest, SearchResponse, SearchResultItem
from app.services.embedding_service import generate_query_embedding
from app.services.telegram_links import (
    build_media_download_url,
    build_telegram_message_url,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class SearchServiceError(RuntimeError):
    """Raised when full hybrid search cannot be completed."""


def _empty_response(query: str) -> SearchResponse:
    return SearchResponse(results=[], query=query, total=0)


def _search_offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        value = int(decode_cursor(cursor).get("offset", 0))
    except (CursorError, TypeError, ValueError) as exc:
        raise SearchServiceError("Invalid search cursor") from exc
    if value < 0:
        raise SearchServiceError("Invalid search cursor")
    return value


def _base_where_clauses(
    user_id: UUID,
    request: SearchRequest,
) -> tuple[list[str], dict[str, object]]:
    where_clauses = ["c.user_id = :user_id"]
    offset = _search_offset(request.cursor)
    params: dict[str, object] = {
        "user_id": str(user_id),
        "query": request.query.strip(),
        "query_pattern": f"%{request.query.strip()}%",
        "limit": request.limit + 1,
        "offset": offset,
        "candidate_limit": max(100, (offset + request.limit + 1) * 10),
        "rrf_k": 60.0,
    }
    if request.chat_ids:
        where_clauses.append("m.chat_id = ANY(CAST(:chat_ids AS uuid[]))")
        params["chat_ids"] = [str(chat_id) for chat_id in request.chat_ids]
    if request.date_from:
        where_clauses.append("m.sent_at >= :date_from")
        params["date_from"] = request.date_from
    if request.date_to:
        where_clauses.append("m.sent_at <= :date_to")
        params["date_to"] = request.date_to
    return where_clauses, params


def _normalize_chat_type(value: object) -> ChatType | None:
    if value is None or isinstance(value, ChatType):
        return value
    if isinstance(value, str):
        try:
            return ChatType(value.strip().lower())
        except ValueError:
            logger.warning(
                "Unknown chat_type in search result", extra={"chat_type": value}
            )
    return None


def _rows_to_response(
    rows: list,
    query: str,
    user_id: UUID,
    *,
    limit: int,
    offset: int,
) -> SearchResponse:
    has_more = len(rows) > limit
    rows = rows[:limit]
    results = []
    for row in rows:
        chat_type = _normalize_chat_type(row.chat_type)
        media_cached = bool(getattr(row, "media_cached", False))
        results.append(
            SearchResultItem(
                id=row.id,
                chat_id=row.chat_id,
                chat_title=row.chat_title,
                chat_type=chat_type,
                chat_telegram_id=row.chat_telegram_id,
                chat_username=row.chat_username,
                telegram_message_id=row.telegram_message_id,
                text=row.text,
                sender_name=row.sender_name,
                is_outgoing=row.is_outgoing,
                sent_at=row.sent_at,
                similarity=float(row.similarity),
                has_media=row.has_media,
                media_type=row.media_type,
                content_summary=getattr(row, "content_summary", None),
                content_preview=getattr(row, "content_preview", None),
                media_processing_status=getattr(row, "media_processing_status", None),
                media_file_name=getattr(row, "media_file_name", None),
                media_mime_type=getattr(row, "media_mime_type", None),
                media_file_size=getattr(row, "media_file_size", None),
                visible_urls=getattr(row, "visible_urls", None) or [],
                hidden_urls=getattr(row, "hidden_urls", None) or [],
                deleted_at=getattr(row, "deleted_at", None),
                transcribed_at=row.transcribed_at,
                telegram_message_url=build_telegram_message_url(
                    chat_type=chat_type,
                    telegram_chat_id=row.chat_telegram_id,
                    username=row.chat_username,
                    message_id=row.telegram_message_id,
                ),
                media_download_url=(
                    build_media_download_url(
                        base_path=(
                            f"/api/v1/chats/{row.chat_id}/messages/"
                            f"{row.telegram_message_id}/media"
                        ),
                        user_id=user_id,
                        chat_id=row.chat_id,
                        telegram_message_id=row.telegram_message_id,
                    )
                    if media_cached
                    else None
                ),
            )
        )
    return SearchResponse(
        results=results,
        query=query,
        total=len(results),
        has_more=has_more,
        next_cursor=(
            encode_cursor({"offset": offset + len(results)}) if has_more else None
        ),
    )


def _hybrid_search_sql(dimensions: int, where_sql: str):
    """Build simple-FTS + trigram + pgvector retrieval fused with RRF."""
    return text(f"""
        WITH search_query AS (
            SELECT websearch_to_tsquery('simple', :query) AS tsq
        ),
        lexical_raw AS (
            SELECT
                m.id AS message_id,
                greatest(
                    ts_rank_cd(m.search_vector, q.tsq, 32),
                    similarity(m.media_file_name, :query),
                    similarity(m.searchable_metadata, :query),
                    CASE WHEN m.media_file_name ILIKE :query_pattern
                        THEN 1.5 ELSE 0 END,
                    CASE WHEN m.searchable_metadata ILIKE :query_pattern
                        THEN 1.5 ELSE 0 END
                ) AS lexical_score,
                left(m.content_text, 1200) AS matched_content
            FROM telegram_messages m
            JOIN telegram_chats c ON c.id = m.chat_id
            CROSS JOIN search_query q
            WHERE {where_sql}
              AND (
                m.search_vector @@ q.tsq
                OR m.media_file_name ILIKE :query_pattern
                OR m.searchable_metadata ILIKE :query_pattern
                OR similarity(m.media_file_name, :query) > 0.2
                OR similarity(m.searchable_metadata, :query) > 0.2
              )
            UNION ALL
            SELECT
                m.id AS message_id,
                ts_rank_cd(mc.search_vector, q.tsq, 32) AS lexical_score,
                left(mc.text, 1200) AS matched_content
            FROM message_content_chunks mc
            JOIN telegram_messages m ON m.id = mc.message_id
            JOIN telegram_chats c ON c.id = m.chat_id
            CROSS JOIN search_query q
            WHERE {where_sql} AND mc.search_vector @@ q.tsq
        ),
        lexical_best AS (
            SELECT DISTINCT ON (message_id)
                message_id, lexical_score, matched_content
            FROM lexical_raw
            ORDER BY message_id, lexical_score DESC
        ),
        lexical_ranked AS (
            SELECT
                message_id,
                row_number() OVER (
                    ORDER BY lexical_score DESC, message_id DESC
                ) AS lexical_rank,
                matched_content
            FROM lexical_best
            ORDER BY lexical_score DESC, message_id DESC
            LIMIT :candidate_limit
        ),
        vector_raw AS (
            SELECT
                m.id AS message_id,
                1 - (m.embedding <=> cast(:embedding AS vector({dimensions})))
                    AS vector_score,
                NULL::text AS matched_content
            FROM telegram_messages m
            JOIN telegram_chats c ON c.id = m.chat_id
            WHERE {where_sql} AND m.embedding IS NOT NULL
            ORDER BY m.embedding <=> cast(:embedding AS vector({dimensions}))
            LIMIT :candidate_limit
        ),
        vector_chunks AS (
            SELECT
                m.id AS message_id,
                1 - (mc.embedding <=> cast(:embedding AS vector({dimensions})))
                    AS vector_score,
                left(mc.text, 1200) AS matched_content
            FROM message_content_chunks mc
            JOIN telegram_messages m ON m.id = mc.message_id
            JOIN telegram_chats c ON c.id = m.chat_id
            WHERE {where_sql} AND mc.embedding IS NOT NULL
            ORDER BY mc.embedding <=> cast(:embedding AS vector({dimensions}))
            LIMIT :candidate_limit
        ),
        vector_best AS (
            SELECT DISTINCT ON (message_id)
                message_id, vector_score, matched_content
            FROM (
                SELECT * FROM vector_raw
                UNION ALL
                SELECT * FROM vector_chunks
            ) candidates
            ORDER BY message_id, vector_score DESC
        ),
        vector_ranked AS (
            SELECT
                message_id,
                row_number() OVER (
                    ORDER BY vector_score DESC, message_id DESC
                ) AS vector_rank,
                matched_content
            FROM vector_best
            ORDER BY vector_score DESC, message_id DESC
            LIMIT :candidate_limit
        ),
        fused AS (
            SELECT
                coalesce(l.message_id, v.message_id) AS message_id,
                (
                    coalesce(1.0 / (:rrf_k + l.lexical_rank), 0) +
                    coalesce(1.0 / (:rrf_k + v.vector_rank), 0)
                ) / (2.0 / (:rrf_k + 1.0)) AS similarity,
                coalesce(l.matched_content, v.matched_content) AS matched_content
            FROM lexical_ranked l
            FULL OUTER JOIN vector_ranked v ON v.message_id = l.message_id
        )
        SELECT
            m.id,
            m.chat_id,
            c.title AS chat_title,
            c.chat_type AS chat_type,
            c.telegram_chat_id AS chat_telegram_id,
            c.username AS chat_username,
            m.telegram_message_id,
            m.text,
            m.sender_name,
            m.is_outgoing,
            m.sent_at,
            fused.similarity,
            m.has_media,
            m.media_type,
            m.content_summary,
            coalesce(fused.matched_content, left(m.content_text, 1200))
                AS content_preview,
            m.media_processing_status,
            m.media_file_name,
            m.media_mime_type,
            m.media_file_size,
            m.visible_urls,
            m.hidden_urls,
            m.deleted_at,
            m.transcribed_at,
            (mo.relative_path IS NOT NULL AND mo.sha256 IS NOT NULL) AS media_cached
        FROM fused
        JOIN telegram_messages m ON m.id = fused.message_id
        JOIN telegram_chats c ON c.id = m.chat_id
        LEFT JOIN media_objects mo ON mo.message_id = m.id
        ORDER BY similarity DESC, m.sent_at DESC, m.telegram_message_id DESC
        LIMIT :limit
        OFFSET :offset
    """)


async def semantic_search(
    db: AsyncSession,
    user_id: UUID,
    request: SearchRequest,
) -> SearchResponse:
    """Run mandatory lexical/vector retrieval and Reciprocal Rank Fusion."""
    normalized_query = request.query.strip()
    if not normalized_query:
        logger.info(
            "Search skipped for blank query",
            extra={"user_id": str(user_id), "query_length": 0},
        )
        return _empty_response(request.query)
    try:
        query_embedding = await generate_query_embedding(normalized_query)
    except Exception as exc:
        logger.exception(
            "Hybrid search embedding generation failed",
            extra={"user_id": str(user_id), "query_length": len(normalized_query)},
        )
        raise SearchServiceError(
            "Hybrid search is unavailable because query embedding failed"
        ) from exc
    if not query_embedding:
        raise SearchServiceError(
            "Hybrid search is unavailable because query embedding was empty"
        )

    where_clauses, params = _base_where_clauses(user_id, request)
    params["embedding"] = "[" + ",".join(str(value) for value in query_embedding) + "]"
    sql = _hybrid_search_sql(
        settings.embedding_dimensions,
        " AND ".join(where_clauses),
    )
    try:
        await db.execute(text("SET LOCAL hnsw.iterative_scan = 'strict_order'"))
        result = await db.execute(sql, params)
    except Exception as exc:
        logger.exception(
            "Hybrid lexical/vector query failed",
            extra={"user_id": str(user_id), "query_length": len(normalized_query)},
        )
        raise SearchServiceError("Hybrid search is temporarily unavailable") from exc
    return _rows_to_response(
        result.fetchall(),
        request.query,
        user_id,
        limit=request.limit,
        offset=int(params["offset"]),
    )


async def get_recent_messages(
    db: AsyncSession,
    user_id: UUID,
    chat_id: UUID | None = None,
    hours: int = 24,
    limit: int = 100,
) -> list[TelegramMessage]:
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
    result = await db.execute(
        query.order_by(TelegramMessage.sent_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
