from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.chat import ChatType, TelegramChat
from app.models.message import TelegramMessage
from app.schemas.chat import ChatListResponse, ChatResponse
from app.schemas.message import MessageListResponse, MessageResponse
from app.services.sync_service import sync_chats

router = APIRouter()


@router.get("", response_model=ChatListResponse)
async def list_chats(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    chat_type: ChatType | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> ChatListResponse:
    """List user's synced chats."""
    query = select(TelegramChat).where(TelegramChat.user_id == user.id)

    if chat_type:
        query = query.where(TelegramChat.chat_type == chat_type)

    query = query.order_by(TelegramChat.title).offset(offset).limit(limit)

    result = await db.execute(query)
    chats = result.scalars().all()

    # Get total count
    count_query = select(func.count()).select_from(TelegramChat).where(
        TelegramChat.user_id == user.id
    )
    if chat_type:
        count_query = count_query.where(TelegramChat.chat_type == chat_type)
    total = (await db.execute(count_query)).scalar()

    return ChatListResponse(
        chats=[ChatResponse.model_validate(chat) for chat in chats],
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    return ChatResponse.model_validate(chat)


@router.get("/{chat_id}/messages", response_model=MessageListResponse)
async def get_chat_messages(
    chat_id: UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> MessageListResponse:
    """Get messages for a chat."""
    # Verify chat ownership
    result = await db.execute(
        select(TelegramChat).where(
            TelegramChat.id == chat_id,
            TelegramChat.user_id == user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

    # Get messages
    query = (
        select(TelegramMessage)
        .where(TelegramMessage.chat_id == chat_id)
        .order_by(TelegramMessage.sent_at.desc())
        .offset(offset)
        .limit(limit + 1)  # Fetch one extra to check if there are more
    )

    result = await db.execute(query)
    messages = result.scalars().all()

    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]

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
            )
            for msg in messages
        ],
        total=None,
        has_more=has_more,
    )
