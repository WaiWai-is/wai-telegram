"""Find shared files through the conversation around them.

Photos carry no filename, and plenty of documents are sent with no caption, so
searching message text alone never reaches them. What people do remember is the
exchange: "the estimate Andrey sent in March". This locates that exchange with
the existing hybrid search, then returns the files sitting next to it, so the
caller gets links to download rather than a transcription bill.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import TelegramChat
from app.models.media import MediaObject
from app.models.message import TelegramMessage
from app.schemas.search import SearchRequest
from app.services.search_service import semantic_search
from app.services.telegram_links import (
    build_media_download_url,
    build_telegram_message_url,
)

FILE_MEDIA_TYPES = ("document", "photo", "video", "audio", "other")

# Telegram ids are per-chat and monotonic, so a window over them is a cheap
# stand-in for "messages sent around this one" without a second time-ordered scan.
DEFAULT_CONTEXT_WINDOW = 6
MAX_CONTEXT_WINDOW = 40


@dataclass(frozen=True)
class _Hit:
    chat_id: UUID
    telegram_message_id: int
    text: str | None
    rank: int


def _context_snippet(text: str | None, limit: int = 300) -> str | None:
    if not text:
        return None
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


async def find_files(
    db: AsyncSession,
    user_id: UUID,
    *,
    query: str,
    media_types: list[str] | None = None,
    chat_ids: list[UUID] | None = None,
    chat_types: list[str] | None = None,
    date_from: Any = None,
    date_to: Any = None,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    limit: int = 20,
) -> dict[str, Any]:
    window = max(0, min(int(context_window), MAX_CONTEXT_WINDOW))
    wanted = [t for t in (media_types or FILE_MEDIA_TYPES) if t in FILE_MEDIA_TYPES]
    if not wanted:
        wanted = list(FILE_MEDIA_TYPES)

    search = await semantic_search(
        db,
        user_id,
        SearchRequest(
            query=query,
            chat_ids=chat_ids,
            chat_types=chat_types,
            date_from=date_from,
            date_to=date_to,
            # Widen the conversational net: each hit may contribute several files,
            # and files far from any hit are worse answers than a shallower sweep.
            limit=min(100, max(limit * 3, 30)),
        ),
    )
    hits = [
        _Hit(item.chat_id, item.telegram_message_id, item.text, rank)
        for rank, item in enumerate(search.results)
    ]
    if not hits:
        return {"files": [], "query": query, "total": 0, "searched_messages": 0}

    conditions = [
        and_(
            TelegramMessage.chat_id == hit.chat_id,
            TelegramMessage.telegram_message_id.between(
                hit.telegram_message_id - window,
                hit.telegram_message_id + window,
            ),
        )
        for hit in hits
    ]
    rows = (
        await db.execute(
            select(TelegramMessage, TelegramChat, MediaObject)
            .join(TelegramChat, TelegramChat.id == TelegramMessage.chat_id)
            .outerjoin(MediaObject, MediaObject.message_id == TelegramMessage.id)
            .where(
                TelegramChat.user_id == user_id,
                TelegramMessage.has_media.is_(True),
                TelegramMessage.media_type.in_(wanted),
                TelegramMessage.deleted_at.is_(None),
                or_(*conditions),
            )
        )
    ).all()

    # A file that matched directly often has no caption of its own, and a photo
    # never has a filename either, so the result would carry nothing a person can
    # judge. Collect the talking around each window and quote the nearest line.
    context_rows = (
        await db.execute(
            select(
                TelegramMessage.chat_id,
                TelegramMessage.telegram_message_id,
                TelegramMessage.text,
            )
            .join(TelegramChat, TelegramChat.id == TelegramMessage.chat_id)
            .where(
                TelegramChat.user_id == user_id,
                TelegramMessage.text.isnot(None),
                TelegramMessage.text != "",
                TelegramMessage.deleted_at.is_(None),
                or_(*conditions),
            )
        )
    ).all()
    context_by_chat: dict[UUID, list[tuple[int, str]]] = {}
    for chat_id, telegram_message_id, text in context_rows:
        context_by_chat.setdefault(chat_id, []).append((telegram_message_id, text))

    def nearest_context(chat_id: UUID, telegram_message_id: int) -> str | None:
        candidates = context_by_chat.get(chat_id) or []
        if not candidates:
            return None
        tid, text = min(candidates, key=lambda row: abs(row[0] - telegram_message_id))
        if abs(tid - telegram_message_id) > window:
            return None
        return _context_snippet(text)

    best: dict[UUID, dict[str, Any]] = {}
    for message, chat, media_object in rows:
        nearest = min(
            (
                hit
                for hit in hits
                if hit.chat_id == message.chat_id
                and abs(hit.telegram_message_id - message.telegram_message_id) <= window
            ),
            key=lambda hit: (
                abs(hit.telegram_message_id - message.telegram_message_id),
                hit.rank,
            ),
            default=None,
        )
        if nearest is None:
            continue
        distance = abs(nearest.telegram_message_id - message.telegram_message_id)
        entry = {
            "message_id": str(message.id),
            "chat_id": str(message.chat_id),
            "chat_title": chat.title,
            "telegram_message_id": message.telegram_message_id,
            "media_type": message.media_type,
            "file_name": (
                (media_object.file_name if media_object else None)
                or message.media_file_name
            ),
            "mime_type": message.media_mime_type,
            "file_size": message.media_file_size,
            "caption": _context_snippet(message.text),
            "sender_name": message.sender_name,
            "sent_at": message.sent_at.isoformat(),
            "matched_because": (
                _context_snippet(nearest.text)
                or _context_snippet(message.text)
                or nearest_context(message.chat_id, message.telegram_message_id)
            ),
            "matched_distance": distance,
            "is_direct_match": distance == 0,
            "telegram_url": build_telegram_message_url(
                chat_type=chat.chat_type,
                telegram_chat_id=chat.telegram_chat_id,
                username=chat.username,
                message_id=message.telegram_message_id,
            ),
            "download_url": (
                build_media_download_url(
                    base_path=(
                        f"/api/v1/chats/{message.chat_id}/messages/"
                        f"{message.telegram_message_id}/media"
                    ),
                    user_id=user_id,
                    chat_id=message.chat_id,
                    telegram_message_id=message.telegram_message_id,
                )
                if media_object and media_object.relative_path and media_object.sha256
                else None
            ),
            "_rank": (distance, nearest.rank),
        }
        previous = best.get(message.id)
        if previous is None or entry["_rank"] < previous["_rank"]:
            best[message.id] = entry

    ordered = sorted(best.values(), key=lambda entry: entry.pop("_rank"))
    return {
        "files": ordered[:limit],
        "query": query,
        "total": len(ordered),
        "searched_messages": len(hits),
    }
