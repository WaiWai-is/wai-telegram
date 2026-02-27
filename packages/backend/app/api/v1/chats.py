from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.cursor import (
    CursorError,
    decode_cursor,
    encode_cursor,
    parse_cursor_datetime,
)
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.chat import ChatType, TelegramChat
from app.models.message import TelegramMessage
from app.schemas.chat import ChatListResponse, ChatResponse
from app.schemas.message import MessageListResponse, MessageResponse
from app.services.sync_service import sync_chats

router = APIRouter()
_CURSOR_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _decode_chat_cursor(cursor: str) -> dict[str, Any]:
    try:
        payload = decode_cursor(cursor)
        raw_last_message_id = payload.get("last_message_id")
        if raw_last_message_id is not None:
            raw_last_message_id = int(raw_last_message_id)
        return {
            "last_activity_at": parse_cursor_datetime(payload.get("last_activity_at")),
            "last_message_id": raw_last_message_id,
            "id": UUID(payload["id"]),
        }
    except (KeyError, TypeError, ValueError, CursorError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid chat cursor",
        ) from exc


def _encode_chat_cursor(chat: TelegramChat) -> str:
    return encode_cursor(
        {
            "last_activity_at": chat.last_activity_at.isoformat()
            if chat.last_activity_at
            else None,
            "last_message_id": chat.last_message_id,
            "id": str(chat.id),
        }
    )


def _decode_message_cursor(cursor: str) -> dict[str, Any]:
    try:
        payload = decode_cursor(cursor)
        sent_at = parse_cursor_datetime(payload["sent_at"])
        if sent_at is None:
            raise CursorError("Missing sent_at")
        return {
            "sent_at": sent_at,
            "telegram_message_id": int(payload["telegram_message_id"]),
            "id": UUID(payload["id"]),
        }
    except (KeyError, TypeError, ValueError, CursorError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid message cursor",
        ) from exc


def _encode_message_cursor(message: TelegramMessage) -> str:
    return encode_cursor(
        {
            "sent_at": message.sent_at.isoformat(),
            "telegram_message_id": message.telegram_message_id,
            "id": str(message.id),
        }
    )


@router.get("", response_model=ChatListResponse)
async def list_chats(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    chat_type: ChatType | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
) -> ChatListResponse:
    """List user's synced chats (cursor pagination, offset fallback)."""
    query = select(TelegramChat).where(TelegramChat.user_id == user.id)

    if chat_type:
        query = query.where(TelegramChat.chat_type == chat_type)

    query = query.order_by(
        TelegramChat.last_activity_at.desc().nulls_last(),
        TelegramChat.last_message_id.desc().nulls_last(),
        TelegramChat.id.desc(),
    )

    if cursor:
        c = _decode_chat_cursor(cursor)
        query = query.where(
            tuple_(
                func.coalesce(TelegramChat.last_activity_at, _CURSOR_EPOCH),
                func.coalesce(TelegramChat.last_message_id, -1),
                TelegramChat.id,
            )
            < (
                c["last_activity_at"] or _CURSOR_EPOCH,
                c["last_message_id"] if c["last_message_id"] is not None else -1,
                c["id"],
            )
        )
    elif offset:
        # Backward compatibility fallback for clients still using offset.
        query = query.offset(offset)

    query = query.limit(limit + 1)

    result = await db.execute(query)
    chats = result.scalars().all()
    has_more = len(chats) > limit
    if has_more:
        chats = chats[:limit]
    next_cursor = _encode_chat_cursor(chats[-1]) if has_more and chats else None

    # Backward compatibility total count.
    count_query = (
        select(func.count())
        .select_from(TelegramChat)
        .where(TelegramChat.user_id == user.id)
    )
    if chat_type:
        count_query = count_query.where(TelegramChat.chat_type == chat_type)
    total = (await db.execute(count_query)).scalar()

    return ChatListResponse(
        chats=[ChatResponse.model_validate(chat) for chat in chats],
        has_more=has_more,
        next_cursor=next_cursor,
        total=total,
    )


@router.post("/refresh", response_model=ChatListResponse)
@limiter.limit("10/minute")
async def refresh_chats(
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ChatListResponse:
    """Refresh chat list from Telegram."""
    chats = await sync_chats(db, user.id)
    return ChatListResponse(
        chats=[ChatResponse.model_validate(chat) for chat in chats],
        has_more=False,
        next_cursor=None,
        total=len(chats),
    )


@router.get("/{chat_id}", response_model=ChatResponse)
async def get_chat(
    chat_id: UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ChatResponse:
    """Get chat details."""
    result = await db.execute(
        select(TelegramChat).where(
            TelegramChat.id == chat_id,
            TelegramChat.user_id == user.id,
        )
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found"
        )
    return ChatResponse.model_validate(chat)


@router.get("/{chat_id}/messages", response_model=MessageListResponse)
async def get_chat_messages(
    chat_id: UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=500),
    before: str | None = Query(default=None),
    after: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
) -> MessageListResponse:
    """Get messages for a chat (cursor pagination, offset fallback)."""
    # Verify chat ownership and get chat metadata
    result = await db.execute(
        select(TelegramChat).where(
            TelegramChat.id == chat_id,
            TelegramChat.user_id == user.id,
        )
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found"
        )

    if after:
        # Fetch messages NEWER than the cursor (ascending, then reverse)
        c = _decode_message_cursor(after)
        query = (
            select(TelegramMessage)
            .where(TelegramMessage.chat_id == chat_id)
            .where(
                tuple_(
                    TelegramMessage.sent_at,
                    TelegramMessage.telegram_message_id,
                    TelegramMessage.id,
                )
                > (c["sent_at"], c["telegram_message_id"], c["id"])
            )
            .order_by(
                TelegramMessage.sent_at.asc(),
                TelegramMessage.telegram_message_id.asc(),
                TelegramMessage.id.asc(),
            )
            .limit(limit + 1)
        )
        result = await db.execute(query)
        messages = list(result.scalars().all())

        has_more = len(messages) > limit
        if has_more:
            messages = messages[:limit]
        # Reverse back to newest-first for consistent response format
        messages.reverse()
        next_cursor = None  # after-based queries don't paginate backwards
        newest_cursor = _encode_message_cursor(messages[0]) if messages else None
    else:
        # Standard newest-first pagination
        query = (
            select(TelegramMessage)
            .where(TelegramMessage.chat_id == chat_id)
            .order_by(
                TelegramMessage.sent_at.desc(),
                TelegramMessage.telegram_message_id.desc(),
                TelegramMessage.id.desc(),
            )
            .limit(limit + 1)
        )

        if before:
            c = _decode_message_cursor(before)
            query = query.where(
                tuple_(
                    TelegramMessage.sent_at,
                    TelegramMessage.telegram_message_id,
                    TelegramMessage.id,
                )
                < (c["sent_at"], c["telegram_message_id"], c["id"])
            )
        elif offset:
            query = query.offset(offset)

        result = await db.execute(query)
        messages = list(result.scalars().all())

        has_more = len(messages) > limit
        if has_more:
            messages = messages[:limit]
        next_cursor = (
            _encode_message_cursor(messages[-1]) if has_more and messages else None
        )
        # newest_cursor is the cursor of the first (newest) message on the first page
        newest_cursor = (
            _encode_message_cursor(messages[0])
            if messages and not before and not offset
            else None
        )

    return MessageListResponse(
        messages=[
            MessageResponse(
                id=msg.id,
                telegram_message_id=msg.telegram_message_id,
                text=msg.text,
                has_media=msg.has_media,
                media_type=msg.media_type,
                sender_id=msg.sender_id,
                sender_name=msg.sender_name,
                is_outgoing=msg.is_outgoing,
                sent_at=msg.sent_at,
                has_embedding=msg.embedding is not None,
                transcribed_at=msg.transcribed_at,
            )
            for msg in messages
        ],
        total=None,
        has_more=has_more,
        next_cursor=next_cursor,
        newest_cursor=newest_cursor,
        total_messages_synced=chat.total_messages_synced,
        last_sync_at=chat.last_sync_at,
    )
