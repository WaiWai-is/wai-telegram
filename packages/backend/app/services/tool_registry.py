"""One owner-scoped Telegram data tool registry for every agent surface."""

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.api_key import ApiKey
from app.models.chat import TelegramChat
from app.models.media import MediaObject, MediaObjectStatus, TranscriptSegment
from app.models.message import MediaProcessingStatus, TelegramMessage
from app.models.session import TelegramSession
from app.models.user import User
from app.schemas.search import SearchRequest
from app.services.media_cache_service import (
    get_or_create_media_object,
    media_preparation_needs_enqueue,
)
from app.services.messaging_service import save_draft as save_telegram_draft
from app.services.file_search_service import (
    DEFAULT_CONTEXT_WINDOW,
    FILE_MEDIA_TYPES,
    MAX_CONTEXT_WINDOW,
    find_files,
)
from app.services.search_service import semantic_search
from app.services.telegram_links import (
    build_media_download_url,
    build_telegram_message_url,
)

settings = get_settings()


class ToolInputError(ValueError):
    pass


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]

    def responses_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


_MESSAGE_LOCATOR = {
    "chat_id": {"type": "string", "format": "uuid"},
    "telegram_message_id": {"type": "integer", "minimum": 1},
}

TOOL_DEFINITIONS = (
    ToolDefinition(
        "find_files",
        'Find shared files - documents, presentations, photos, videos - through the conversation around them, and return links to open or download each one. Use this when the file itself is the goal and it is remembered by context rather than by name ("the estimate Andrey sent in spring"), since photos have no filename and many documents arrive with no caption. Returns the surrounding message that matched, so the caller can judge relevance. download_url is present only for files already staged on disk, and private chats have no public telegram_url at all - in both cases pass chat_id and telegram_message_id to prepare_media, then download_media. Widen context_window to reach files sent a few messages away from the discussion.',
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "media_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(FILE_MEDIA_TYPES)},
                },
                "chat_ids": {
                    "type": "array",
                    "items": {"type": "string", "format": "uuid"},
                },
                "chat_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["private", "group", "supergroup", "channel"],
                    },
                },
                "date_from": {"type": "string", "format": "date-time"},
                "date_to": {"type": "string", "format": "date-time"},
                "context_window": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": MAX_CONTEXT_WINDOW,
                    "default": DEFAULT_CONTEXT_WINDOW,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    ToolDefinition(
        "search_messages",
        "Search synced messages, links, filenames, transcripts and extracted documents. Use mode=hybrid for a natural-language description and mode=exact for a known literal phrase. Filter by chat_types to restrict private chats, groups, supergroups or channels. Results are cursor-paginated.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "mode": {
                    "type": "string",
                    "enum": ["hybrid", "exact"],
                    "default": "hybrid",
                },
                "chat_ids": {
                    "type": "array",
                    "items": {"type": "string", "format": "uuid"},
                },
                "chat_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["private", "group", "supergroup", "channel"],
                    },
                },
                "date_from": {"type": "string", "format": "date-time"},
                "date_to": {"type": "string", "format": "date-time"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "cursor": {"type": "string"},
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        "get_message",
        "Return full message metadata, URLs, lifecycle, reply/thread/forward/album and media state.",
        {
            "type": "object",
            "properties": _MESSAGE_LOCATOR,
            "required": ["chat_id", "telegram_message_id"],
        },
    ),
    ToolDefinition(
        "save_draft",
        "Save or replace a server-synced Telegram text draft in a chat. This never sends a message and replaces any existing draft in that chat.",
        {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string", "format": "uuid"},
                "text": {"type": "string", "minLength": 1},
            },
            "required": ["chat_id", "text"],
        },
    ),
    ToolDefinition(
        "prepare_media",
        "Idempotently fetch and process original Telegram media. Returns progress and retry_after; historical media is fetched only through this call.",
        {
            "type": "object",
            "properties": _MESSAGE_LOCATOR,
            "required": ["chat_id", "telegram_message_id"],
        },
    ),
    ToolDefinition(
        "download_media",
        "Return filename, MIME, size, SHA-256, signed URL and Telegram link for a cached original. Call prepare_media first on cache miss.",
        {
            "type": "object",
            "properties": _MESSAGE_LOCATOR,
            "required": ["chat_id", "telegram_message_id"],
        },
    ),
    ToolDefinition(
        "get_message_content",
        "Return summary and a cursor-paginated slice of transcript or extracted text, with an explicit next action.",
        {
            "type": "object",
            "properties": {
                **_MESSAGE_LOCATOR,
                "cursor": {"type": "integer", "minimum": 0},
                "limit_chars": {
                    "type": "integer",
                    "minimum": 1000,
                    "maximum": 50000,
                },
            },
            "required": ["chat_id", "telegram_message_id"],
        },
    ),
    ToolDefinition(
        "get_transcript_segments",
        "Return timestamped transcript segments with speaker, confidence and language using sequence cursor pagination.",
        {
            "type": "object",
            "properties": {
                **_MESSAGE_LOCATOR,
                "cursor": {"type": "integer", "minimum": 0},
                "start_ms": {"type": "integer", "minimum": 0},
                "end_ms": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": ["chat_id", "telegram_message_id"],
        },
    ),
    ToolDefinition(
        "get_data_status",
        "Return data freshness, queue depths, persistent cache usage/hit ratio, active auth state and processing breakdown.",
        {"type": "object", "properties": {}},
    ),
)

_DEFINITION_BY_NAME = {definition.name: definition for definition in TOOL_DEFINITIONS}
# Only outbound effects are write-level. Fetching and processing media fills our
# own cache and is invisible to the other side, like sync; a draft is not.
WRITE_TOOL_NAMES = frozenset({"save_draft"})


def responses_tool_definitions(names: set[str] | None = None) -> list[dict[str, Any]]:
    return [
        definition.responses_schema()
        for definition in TOOL_DEFINITIONS
        if names is None or definition.name in names
    ]


def _required_uuid(arguments: dict[str, Any], name: str) -> UUID:
    try:
        return UUID(str(arguments[name]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolInputError(f"{name} must be a UUID") from exc


def _required_int(arguments: dict[str, Any], name: str) -> int:
    try:
        value = int(arguments[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolInputError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ToolInputError(f"{name} must be positive")
    return value


def _required_text(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolInputError(f"{name} must be a non-empty string")
    return value


async def _message_row(
    db: AsyncSession,
    user_id: UUID,
    arguments: dict[str, Any],
) -> tuple[TelegramMessage, TelegramChat, MediaObject | None]:
    chat_id = _required_uuid(arguments, "chat_id")
    telegram_message_id = _required_int(arguments, "telegram_message_id")
    row = (
        await db.execute(
            select(TelegramMessage, TelegramChat, MediaObject)
            .join(TelegramChat, TelegramChat.id == TelegramMessage.chat_id)
            .outerjoin(MediaObject, MediaObject.message_id == TelegramMessage.id)
            .where(
                TelegramChat.user_id == user_id,
                TelegramMessage.chat_id == chat_id,
                TelegramMessage.telegram_message_id == telegram_message_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise ToolInputError("Message not found")
    return row


def _telegram_url(message: TelegramMessage, chat: TelegramChat) -> str | None:
    return build_telegram_message_url(
        chat_type=chat.chat_type,
        telegram_chat_id=chat.telegram_chat_id,
        username=chat.username,
        message_id=message.telegram_message_id,
    )


def _download_url(
    user_id: UUID,
    message: TelegramMessage,
    media_object: MediaObject | None,
) -> str | None:
    if not media_object or not media_object.relative_path or not media_object.sha256:
        return None
    return build_media_download_url(
        base_path=(
            f"/api/v1/chats/{message.chat_id}/messages/"
            f"{message.telegram_message_id}/media"
        ),
        user_id=user_id,
        chat_id=message.chat_id,
        telegram_message_id=message.telegram_message_id,
    )


async def _search_messages(
    db: AsyncSession, user_id: UUID, arguments: dict[str, Any]
) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ToolInputError("query is required")
    request = SearchRequest(
        query=query,
        mode=arguments.get("mode", "hybrid"),
        chat_ids=arguments.get("chat_ids"),
        chat_types=arguments.get("chat_types"),
        date_from=arguments.get("date_from"),
        date_to=arguments.get("date_to"),
        limit=arguments.get("limit", 20),
        cursor=arguments.get("cursor"),
    )
    response = await semantic_search(db, user_id, request)
    return response.model_dump(mode="json")


async def _find_files(
    db: AsyncSession, user_id: UUID, arguments: dict[str, Any]
) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ToolInputError("query is required")
    return await find_files(
        db,
        user_id,
        query=query,
        media_types=arguments.get("media_types"),
        chat_ids=arguments.get("chat_ids"),
        chat_types=arguments.get("chat_types"),
        date_from=arguments.get("date_from"),
        date_to=arguments.get("date_to"),
        context_window=arguments.get("context_window", DEFAULT_CONTEXT_WINDOW),
        limit=arguments.get("limit", 20),
    )


async def _get_message(
    db: AsyncSession, user_id: UUID, arguments: dict[str, Any]
) -> dict[str, Any]:
    message, chat, media_object = await _message_row(db, user_id, arguments)
    return {
        "id": str(message.id),
        "chat_id": str(chat.id),
        "chat_title": chat.title,
        "telegram_message_id": message.telegram_message_id,
        "text": message.text,
        "sender_id": message.sender_id,
        "sender_name": message.sender_name,
        "is_outgoing": message.is_outgoing,
        "sent_at": message.sent_at.isoformat(),
        "edited_at": message.edited_at.isoformat() if message.edited_at else None,
        "deleted_at": message.deleted_at.isoformat() if message.deleted_at else None,
        "entities": message.entities or [],
        "visible_urls": message.visible_urls or [],
        "hidden_urls": message.hidden_urls or [],
        "buttons": message.buttons or [],
        "webpage_preview": message.webpage_preview,
        "reply_to_message_id": message.reply_to_message_id,
        "thread_id": message.thread_id,
        "forward_origin": message.forward_origin,
        "album_id": message.album_id,
        "reactions": message.reactions or [],
        "poll": message.poll,
        "contact": message.contact,
        "location": message.location,
        "service_event": message.service_event,
        "has_media": message.has_media,
        "media_type": message.media_type,
        "media_file_name": message.media_file_name,
        "media_mime_type": message.media_mime_type,
        "media_file_size": message.media_file_size,
        "media_processing_status": str(message.media_processing_status)
        if message.media_processing_status
        else None,
        "media_cache_status": str(media_object.status) if media_object else None,
        "media_cache_stage": str(media_object.stage) if media_object else None,
        "media_cached_bytes": media_object.byte_offset if media_object else 0,
        "media_sha256": media_object.sha256 if media_object else None,
        "telegram_message_url": _telegram_url(message, chat),
        "media_download_url": _download_url(user_id, message, media_object),
    }


async def _save_draft(
    db: AsyncSession, user_id: UUID, arguments: dict[str, Any]
) -> dict[str, Any]:
    chat_id = _required_uuid(arguments, "chat_id")
    text = _required_text(arguments, "text")
    try:
        return await save_telegram_draft(db, user_id, chat_id, text)
    except ValueError as exc:
        raise ToolInputError(str(exc)) from exc


async def _prepare_media(
    db: AsyncSession, user_id: UUID, arguments: dict[str, Any]
) -> dict[str, Any]:
    message, chat, media_object = await _message_row(db, user_id, arguments)
    if not message.has_media:
        raise ToolInputError("Message has no media")
    if not settings.media_pipeline_enabled:
        return {
            "message_id": str(message.id),
            "status": "unavailable",
            "stage": "deferred",
            "enqueued": False,
            "error_code": "media_pipeline_deferred",
            "error_detail": (
                "Durable media processing is deferred until storage is attached"
            ),
            "retry_after": None,
            "media_download_url": None,
            "telegram_message_url": _telegram_url(message, chat),
            "next_action": "Retry after the durable media pipeline is enabled",
        }
    if media_object is None:
        media_object = await get_or_create_media_object(db, user_id, message.id)

    enqueued = False
    if media_preparation_needs_enqueue(message, media_object):
        from app.tasks.media_tasks import enqueue_media_processing

        message.media_processing_status = MediaProcessingStatus.PENDING
        message.media_processing_error_code = None
        message.media_processing_error = None
        media_object.status = MediaObjectStatus.PENDING
        media_object.error_code = None
        media_object.error_detail = None
        await db.commit()
        enqueue_media_processing([message.id])
        enqueued = True

    return {
        "message_id": str(message.id),
        "status": str(media_object.status),
        "stage": str(media_object.stage),
        "byte_offset": media_object.byte_offset,
        "size_bytes": media_object.size_bytes,
        "sha256": media_object.sha256,
        "retry_after": media_object.retry_after.isoformat()
        if media_object.retry_after
        else None,
        "error_code": media_object.error_code,
        "error_detail": media_object.error_detail,
        "enqueued": enqueued,
        "media_download_url": _download_url(user_id, message, media_object),
        "telegram_message_url": _telegram_url(message, chat),
        "next_action": (
            "Call download_media"
            if media_object.relative_path and media_object.sha256
            else "Call prepare_media again after retry_after to refresh progress"
        ),
    }


async def _download_media(
    db: AsyncSession, user_id: UUID, arguments: dict[str, Any]
) -> dict[str, Any]:
    message, chat, media_object = await _message_row(db, user_id, arguments)
    url = _download_url(user_id, message, media_object)
    if url is None:
        return {
            "status": "cache_miss",
            "telegram_message_id": message.telegram_message_id,
            "telegram_message_url": _telegram_url(message, chat),
            "next_action": "Call prepare_media, then retry download_media",
        }
    return {
        "status": "ready",
        "telegram_message_id": message.telegram_message_id,
        "media_file_name": media_object.file_name or message.media_file_name,
        "media_mime_type": media_object.mime_type or message.media_mime_type,
        "media_file_size": media_object.size_bytes or message.media_file_size,
        "media_sha256": media_object.sha256,
        "media_download_url": url,
        "telegram_message_url": _telegram_url(message, chat),
        "next_action": "Download the resource_link; call download_media again to refresh the signed URL",
    }


async def _get_message_content(
    db: AsyncSession, user_id: UUID, arguments: dict[str, Any]
) -> dict[str, Any]:
    message, chat, media_object = await _message_row(db, user_id, arguments)
    cursor = max(0, int(arguments.get("cursor", 0)))
    limit_chars = min(50_000, max(1_000, int(arguments.get("limit_chars", 20_000))))
    full_text = message.content_text or ""
    content = full_text[cursor : cursor + limit_chars]
    next_cursor = cursor + len(content)
    has_more = next_cursor < len(full_text)
    if message.media_processing_status == MediaProcessingStatus.READY:
        next_action = (
            "Call get_message_content with next_cursor"
            if has_more
            else "Content is complete"
        )
    elif media_object and media_object.status in {
        MediaObjectStatus.FETCHING,
        MediaObjectStatus.EXTRACTING,
        MediaObjectStatus.INDEXING,
        MediaObjectStatus.PROCESSING,
        MediaObjectStatus.RETRY_WAIT,
    }:
        next_action = "Call prepare_media again after retry_after"
    elif message.has_media:
        next_action = "Call prepare_media"
    else:
        next_action = "No media content is available"
    return {
        "message_id": str(message.id),
        "telegram_message_id": message.telegram_message_id,
        "text": message.text,
        "media_type": message.media_type,
        "media_file_name": message.media_file_name,
        "media_mime_type": message.media_mime_type,
        "media_file_size": message.media_file_size,
        "content_summary": message.content_summary,
        "content_text": content,
        "cursor": cursor,
        "has_more": has_more,
        "next_cursor": next_cursor if has_more else None,
        "media_processing_status": str(message.media_processing_status)
        if message.media_processing_status
        else None,
        "media_processing_error_code": message.media_processing_error_code,
        "media_cache_status": str(media_object.status) if media_object else None,
        "telegram_message_url": _telegram_url(message, chat),
        "media_download_url": _download_url(user_id, message, media_object),
        "next_action": next_action,
    }


async def _get_transcript_segments(
    db: AsyncSession, user_id: UUID, arguments: dict[str, Any]
) -> dict[str, Any]:
    message, _chat, _media_object = await _message_row(db, user_id, arguments)
    cursor = max(0, int(arguments.get("cursor", 0)))
    limit = min(500, max(1, int(arguments.get("limit", 100))))
    query = select(TranscriptSegment).where(
        TranscriptSegment.message_id == message.id,
        TranscriptSegment.sequence >= cursor,
    )
    if arguments.get("start_ms") is not None:
        query = query.where(TranscriptSegment.end_ms >= int(arguments["start_ms"]))
    if arguments.get("end_ms") is not None:
        query = query.where(TranscriptSegment.start_ms <= int(arguments["end_ms"]))
    rows = list(
        (
            await db.execute(
                query.order_by(TranscriptSegment.sequence).limit(limit + 1)
            )
        ).scalars()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "segments": [
            {
                "sequence": row.sequence,
                "start_ms": row.start_ms,
                "end_ms": row.end_ms,
                "speaker": row.speaker,
                "confidence": row.confidence,
                "language": row.language,
                "text": row.text,
            }
            for row in rows
        ],
        "has_more": has_more,
        "next_cursor": rows[-1].sequence + 1 if has_more and rows else None,
    }


async def _get_data_status(
    db: AsyncSession, user_id: UUID, _arguments: dict[str, Any]
) -> dict[str, Any]:
    chat_count = (
        await db.execute(
            select(func.count())
            .select_from(TelegramChat)
            .where(TelegramChat.user_id == user_id)
        )
    ).scalar_one()
    message_count = (
        await db.execute(
            select(func.count())
            .select_from(TelegramMessage)
            .join(TelegramChat)
            .where(TelegramChat.user_id == user_id)
        )
    ).scalar_one()
    freshest_message = (
        await db.execute(
            select(func.max(TelegramMessage.sent_at))
            .join(TelegramChat)
            .where(TelegramChat.user_id == user_id)
        )
    ).scalar_one()
    processing_rows = (
        await db.execute(
            select(TelegramMessage.media_processing_status, func.count())
            .join(TelegramChat)
            .where(TelegramChat.user_id == user_id)
            .group_by(TelegramMessage.media_processing_status)
        )
    ).all()
    cache_bytes, cache_objects = (
        await db.execute(
            select(
                func.coalesce(func.sum(MediaObject.size_bytes), 0),
                func.count(MediaObject.id),
            ).where(MediaObject.user_id == user_id)
        )
    ).one()
    active_users = (
        await db.execute(
            select(func.count()).select_from(User).where(User.is_active.is_(True))
        )
    ).scalar_one()
    active_sessions = (
        await db.execute(
            select(func.count())
            .select_from(TelegramSession)
            .where(
                TelegramSession.user_id == user_id,
                TelegramSession.is_active.is_(True),
            )
        )
    ).scalar_one()
    active_keys = (
        await db.execute(
            select(func.count())
            .select_from(ApiKey)
            .where(
                ApiKey.user_id == user_id,
                ApiKey.is_active.is_(True),
            )
        )
    ).scalar_one()

    redis_client = aioredis.from_url(settings.redis_url)
    try:
        queue_names = ("celery", "media-fetch", "media-process", "media-index")
        queue_depths = {
            name: int(await redis_client.llen(name)) for name in queue_names
        }
        metrics = await redis_client.hgetall("media:metrics")
    finally:
        await redis_client.aclose()
    hits = int(metrics.get(b"hits", metrics.get("hits", 0)))
    misses = int(metrics.get(b"misses", metrics.get("misses", 0)))
    attempts = hits + misses

    volume = None
    if settings.media_root.exists():
        usage = shutil.disk_usage(settings.media_root)
        volume = {
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_percent": round((usage.used / usage.total) * 100, 2),
        }
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "chats": int(chat_count),
        "messages": int(message_count),
        "freshest_message_at": freshest_message.isoformat()
        if freshest_message
        else None,
        "queue_depths": queue_depths,
        "processing": {
            str(status) if status is not None else "uninitialized": int(count)
            for status, count in processing_rows
        },
        "cache": {
            "pipeline_enabled": settings.media_pipeline_enabled,
            "objects": int(cache_objects),
            "bytes": int(cache_bytes),
            "hits": hits,
            "misses": misses,
            "hit_ratio": (hits / attempts) if attempts else None,
            "volume": volume,
            "eviction_enabled": False,
        },
        "auth": {
            "active_users": int(active_users),
            "active_owner_sessions": int(active_sessions),
            "active_owner_api_keys": int(active_keys),
        },
    }


ToolHandler = Callable[[AsyncSession, UUID, dict[str, Any]], Awaitable[dict[str, Any]]]
_HANDLERS: dict[str, ToolHandler] = {
    "search_messages": _search_messages,
    "find_files": _find_files,
    "get_message": _get_message,
    "save_draft": _save_draft,
    "prepare_media": _prepare_media,
    "download_media": _download_media,
    "get_message_content": _get_message_content,
    "get_transcript_segments": _get_transcript_segments,
    "get_data_status": _get_data_status,
}


async def execute_data_tool(
    db: AsyncSession,
    user_id: UUID,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    if name not in _DEFINITION_BY_NAME:
        raise ToolInputError(f"Unknown data tool: {name}")
    active_user_id = (
        await db.execute(
            select(User.id).where(
                User.id == user_id,
                User.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if active_user_id is None:
        raise ToolInputError("User is inactive")
    return await _HANDLERS[name](db, user_id, arguments)
