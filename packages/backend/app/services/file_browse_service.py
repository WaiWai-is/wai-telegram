"""Browse the files shared in Telegram chats by their own attributes.

A file is usually remembered as a chat, a week and a person - "the PDFs Andrey
sent in March" - not as a sentence someone typed beside it. Routing that through
hybrid search buys an embedding round-trip and a relevance ranking nobody asked
for, and it cannot answer "everything from last week" at all. This walks the
message index directly instead.

The other half of the problem is that historical media lives in Telegram, not on
our disk: a listing that showed only staged files would look empty and lie. So
every entry carries one download_state - ready, fetching, queued, not_prepared,
unavailable - in place of the fourteen-value cache enum, and says in a sentence
what it would take to get the bytes.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cursor import decode_cursor, encode_cursor, parse_cursor_datetime
from app.models.chat import ChatType, TelegramChat
from app.models.media import MediaObject, MediaObjectStatus
from app.models.message import TelegramMessage
from app.services.media_access import MEDIA_DOWNLOAD_TOKEN_TTL
from app.services.telegram_links import (
    build_media_download_url,
    build_telegram_message_url,
)

# Every value get_media_info can write (media_content_service.py:156-213). voice
# and video_note were missing from the old tuple, which made every voice note
# unreachable through the file tools while staying perfectly downloadable.
FILE_MEDIA_TYPES = (
    "document",
    "photo",
    "video",
    "audio",
    "voice",
    "video_note",
    "other",
)
# "other" is a poll, a contact or a location - a message with no bytes behind it.
# Askable on purpose, never part of a listing someone meant as "the files".
DEFAULT_MEDIA_TYPES = FILE_MEDIA_TYPES[:-1]

# Telegram ids are per-chat and monotonic, so a window over them is a cheap
# stand-in for "messages sent around this one" without a second time-ordered scan.
DEFAULT_CONTEXT_WINDOW = 6
MAX_CONTEXT_WINDOW = 40

# A page of files is the largest batch an agent can start. The in-flight ceiling
# counts dispatch claims only - QUEUED and PROCESSING - because PENDING is the
# metered backlog the dispatcher drains at media_dispatch_target_depth, and it
# normally runs to hundreds of thousands of historical files.
MAX_PREPARE_PER_CALL = 25
MAX_LOCATORS = 25
MAX_IN_FLIGHT_MESSAGES = 100
MIN_FREE_BYTES = 2 * 1024**3
LARGE_FILE_BYTES = 200 * 1024**2


# TelegramMessage.embedding is a 1536-dim halfvec and content_text runs to tens of
# thousands of characters; a hundred whole entities would drag megabytes across
# the wire for fifteen scalars.
FILE_COLUMNS = (
    TelegramMessage.id.label("message_id"),
    TelegramMessage.chat_id,
    TelegramMessage.telegram_message_id,
    TelegramMessage.sent_at,
    TelegramMessage.sender_id,
    TelegramMessage.sender_name,
    TelegramMessage.is_outgoing,
    TelegramMessage.text,
    TelegramMessage.media_type,
    TelegramMessage.media_file_name,
    TelegramMessage.media_mime_type,
    TelegramMessage.media_file_size,
    TelegramMessage.media_duration_seconds,
    TelegramMessage.content_summary,
    TelegramMessage.media_processing_status,
    TelegramChat.title.label("chat_title"),
    TelegramChat.chat_type,
    TelegramChat.telegram_chat_id,
    TelegramChat.username,
    MediaObject.relative_path,
    MediaObject.sha256,
    MediaObject.file_name.label("cached_file_name"),
    MediaObject.mime_type.label("cached_mime_type"),
    MediaObject.size_bytes.label("cached_size_bytes"),
    MediaObject.status.label("cache_status"),
    MediaObject.stage.label("cache_stage"),
    MediaObject.byte_offset,
    MediaObject.error_code,
    MediaObject.error_detail,
    MediaObject.retry_after,
)

_KEYSET = (
    TelegramMessage.sent_at,
    TelegramMessage.telegram_message_id,
    TelegramMessage.id,
)


def context_snippet(text: str | None, limit: int = 300) -> str | None:
    if not text:
        return None
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def normalize_media_types(values: Any) -> list[str]:
    """Return the media types to search, refusing anything we cannot look for.

    The old code dropped unknown values and fell back to every type, so asking
    for voice notes quietly returned documents instead. A caller is better served
    by being told the word it used does not exist.
    """
    if values is None:
        return list(DEFAULT_MEDIA_TYPES)
    if not isinstance(values, (list, tuple)):
        raise ValueError("media_types must be an array of strings")
    unknown = sorted({str(value) for value in values} - set(FILE_MEDIA_TYPES))
    if unknown:
        raise ValueError(
            "media_types contains an unknown value: "
            + ", ".join(unknown)
            + ". Allowed: "
            + ", ".join(FILE_MEDIA_TYPES)
        )
    return [str(value) for value in values] or list(DEFAULT_MEDIA_TYPES)


def normalize_extensions(values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise ValueError("extensions must be an array of strings")
    normalized = []
    for value in values:
        cleaned = str(value).strip().lstrip(".").lower()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def derive_download_state(row: Row) -> str:
    """Say whether these bytes can be had, which is nearly always yes.

    The download endpoint serves whatever is staged and streams the rest from
    Telegram, so sitting on our disk stopped being the thing that decides. Only
    a source Telegram itself no longer holds is out of reach; a failed
    extraction, a full volume, or a file nobody ever staged all still download.
    """
    if row.cache_status == MediaObjectStatus.SOURCE_DELETED:
        return "unavailable"
    return "ready"


def _format_size(size: int | None) -> str:
    if not isinstance(size, int) or size <= 0:
        return "unknown size"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return "unknown size"


def _file_next_action(entry: dict[str, Any]) -> str:
    """Say the one thing this file needs next, in the caller's own vocabulary."""
    if entry["download_state"] == "unavailable":
        return "The original was deleted from Telegram. No download is possible."
    if entry["media_type"] == "other":
        return (
            "A poll, contact or location has no file to download. Call get_message "
            "for its payload."
        )
    size = entry.get("media_file_size") or 0
    if size > LARGE_FILE_BYTES:
        return (
            f"Download media_download_url before {entry['download_url_expires_at']}. "
            f"It is large ({_format_size(size)}), so expect the transfer to take "
            "a while."
        )
    return f"Download media_download_url before {entry['download_url_expires_at']}."


def build_file_entry(
    user_id: UUID,
    row: Row,
    *,
    matched_because: str | None = None,
    matched_distance: int | None = None,
) -> dict[str, Any]:
    """Describe one file the same way in every mode, so the shape never shifts."""
    download_state = derive_download_state(row)
    download_url = (
        build_media_download_url(
            base_path=(
                f"/api/v1/chats/{row.chat_id}/messages/{row.telegram_message_id}/media"
            ),
            user_id=user_id,
            chat_id=row.chat_id,
            telegram_message_id=row.telegram_message_id,
        )
        if download_state != "unavailable"
        else None
    )
    chat_type = row.chat_type
    entry: dict[str, Any] = {
        "message_id": str(row.message_id),
        "chat_id": str(row.chat_id),
        "chat_title": row.chat_title,
        "chat_type": (
            chat_type.value if isinstance(chat_type, ChatType) else str(chat_type)
        ),
        "telegram_message_id": row.telegram_message_id,
        "sent_at": row.sent_at.isoformat(),
        "sender_id": row.sender_id,
        "sender_name": row.sender_name,
        "is_outgoing": row.is_outgoing,
        "media_type": row.media_type,
        "media_file_name": row.cached_file_name or row.media_file_name,
        "media_mime_type": row.cached_mime_type or row.media_mime_type,
        "media_file_size": row.cached_size_bytes or row.media_file_size,
        "media_duration_seconds": row.media_duration_seconds,
        "media_sha256": row.sha256,
        "caption": context_snippet(row.text),
        "content_summary": context_snippet(row.content_summary, limit=600),
        "download_state": download_state,
        "media_download_url": download_url,
        "download_url_expires_at": (
            (datetime.now(UTC) + MEDIA_DOWNLOAD_TOKEN_TTL).isoformat()
            if download_url
            else None
        ),
        "media_cache_status": str(row.cache_status) if row.cache_status else None,
        "media_cache_stage": str(row.cache_stage) if row.cache_stage else None,
        "media_cached_bytes": row.byte_offset or 0,
        "media_processing_status": (
            str(row.media_processing_status) if row.media_processing_status else None
        ),
        "error_code": row.error_code,
        "error_detail": row.error_detail,
        "retry_after": row.retry_after.isoformat() if row.retry_after else None,
        "telegram_message_url": build_telegram_message_url(
            chat_type=row.chat_type,
            telegram_chat_id=row.telegram_chat_id,
            username=row.username,
            message_id=row.telegram_message_id,
        ),
        # Present and null outside query mode, so one payload shape serves all three.
        "matched_because": matched_because,
        "matched_distance": matched_distance,
        "is_direct_match": (
            (matched_distance == 0) if matched_distance is not None else None
        ),
    }
    entry["next_action"] = _file_next_action(entry)
    return entry


def encode_file_cursor(row: Row, order: str) -> str:
    return encode_cursor(
        {
            "m": "files",
            "o": order,
            "sent_at": row.sent_at.isoformat(),
            "telegram_message_id": row.telegram_message_id,
            "id": str(row.message_id),
        }
    )


def decode_file_cursor(cursor: str, order: str) -> tuple[datetime, int, UUID]:
    """Refuse a cursor that would walk the listing in the wrong direction."""
    data = decode_cursor(cursor)
    if data.get("m") != "files":
        raise ValueError("cursor is not a file listing cursor; drop it")
    if data.get("o") != order:
        raise ValueError(
            f"cursor was issued for order={data.get('o')!r}; "
            "pass the same order or drop the cursor"
        )
    try:
        return (
            parse_cursor_datetime(data["sent_at"]),
            int(data["telegram_message_id"]),
            UUID(str(data["id"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid file listing cursor") from exc


def apply_file_filters(
    stmt,
    *,
    media_types: list[str],
    chat_ids: list[UUID] | None = None,
    chat_types: list[str] | None = None,
    date_from: Any = None,
    date_to: Any = None,
    extensions: list[str] | None = None,
    file_name: str | None = None,
    sender: str | None = None,
    from_me: bool | None = None,
    max_size_bytes: int | None = None,
):
    """Narrow a media-message select the same way in browse and in query mode."""
    stmt = stmt.where(TelegramMessage.media_type.in_(media_types))
    if chat_ids:
        stmt = stmt.where(TelegramMessage.chat_id.in_(chat_ids))
    if chat_types:
        stmt = stmt.where(
            TelegramChat.chat_type.in_([ChatType(value) for value in chat_types])
        )
    if date_from is not None:
        stmt = stmt.where(TelegramMessage.sent_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(TelegramMessage.sent_at <= date_to)
    if extensions:
        stmt = stmt.where(
            or_(
                *[
                    TelegramMessage.media_file_name.ilike(f"%.{extension}")
                    for extension in extensions
                ]
            )
        )
    if file_name:
        stmt = stmt.where(TelegramMessage.media_file_name.ilike(f"%{file_name}%"))
    if sender:
        stmt = stmt.where(TelegramMessage.sender_name.ilike(f"%{sender}%"))
    if from_me is not None:
        stmt = stmt.where(TelegramMessage.is_outgoing.is_(from_me))
    if max_size_bytes is not None:
        # Telegram sends no size for photos, so an unknown size must not be read
        # as "too big" - that would silently drop most of the corpus.
        size = func.coalesce(MediaObject.size_bytes, TelegramMessage.media_file_size)
        stmt = stmt.where(or_(size.is_(None), size <= max_size_bytes))
    return stmt


def file_select(user_id: UUID):
    return (
        select(*FILE_COLUMNS)
        .join(TelegramChat, TelegramChat.id == TelegramMessage.chat_id)
        .outerjoin(MediaObject, MediaObject.message_id == TelegramMessage.id)
        .where(
            TelegramChat.user_id == user_id,
            TelegramMessage.has_media.is_(True),
            TelegramMessage.deleted_at.is_(None),
        )
    )


async def list_files(
    db: AsyncSession,
    user_id: UUID,
    *,
    media_types: list[str],
    order: str = "newest",
    cursor_values: tuple[datetime, int, UUID] | None = None,
    limit: int = 20,
    **filters: Any,
) -> tuple[list[Row], bool]:
    """Page through media messages newest-first by their own attributes."""
    stmt = apply_file_filters(file_select(user_id), media_types=media_types, **filters)
    if order == "oldest":
        stmt = stmt.order_by(*[key.asc() for key in _KEYSET])
        if cursor_values:
            stmt = stmt.where(tuple_(*_KEYSET) > cursor_values)
    else:
        stmt = stmt.order_by(*[key.desc() for key in _KEYSET])
        if cursor_values:
            stmt = stmt.where(tuple_(*_KEYSET) < cursor_values)
    rows = (await db.execute(stmt.limit(limit + 1))).all()
    return rows[:limit], len(rows) > limit


async def list_files_by_locators(
    db: AsyncSession,
    user_id: UUID,
    locators: list[tuple[UUID, int]],
) -> tuple[list[Row], list[dict[str, Any]]]:
    """Resolve an exact set another tool handed us, keeping the caller's order.

    A locator that no longer resolves is reported rather than raised: one stale
    id out of twenty-five should not cost the caller the other twenty-four.
    """
    stmt = file_select(user_id).where(
        tuple_(TelegramMessage.chat_id, TelegramMessage.telegram_message_id).in_(
            locators
        )
    )
    rows = (await db.execute(stmt)).all()
    by_locator = {(row.chat_id, row.telegram_message_id): row for row in rows}
    found = [by_locator[locator] for locator in locators if locator in by_locator]
    not_found = [
        {"chat_id": str(chat_id), "telegram_message_id": telegram_message_id}
        for chat_id, telegram_message_id in locators
        if (chat_id, telegram_message_id) not in by_locator
    ]
    return found, not_found
