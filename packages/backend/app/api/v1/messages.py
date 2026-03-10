from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.database import get_db
from app.core.limiter import limiter
from app.schemas.messaging import (
    ReplyMessageRequest,
    SendFileRequest,
    SendFileResponse,
    SendMessageRequest,
    SendMessageResponse,
)
from app.services.messaging_service import (
    reply_to_message,
    send_file,
    send_message,
)

router = APIRouter()


@router.post("/{chat_id}/send", response_model=SendMessageResponse)
@limiter.limit("20/minute")
async def send_message_endpoint(
    request: Request,
    chat_id: UUID,
    body: SendMessageRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SendMessageResponse:
    """Send a text message to a Telegram chat."""
    try:
        result = await send_message(db, user.id, chat_id, body.text)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return SendMessageResponse(**result)


@router.post("/{chat_id}/send-file", response_model=SendFileResponse)
@limiter.limit("10/minute")
async def send_file_endpoint(
    request: Request,
    chat_id: UUID,
    body: SendFileRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SendFileResponse:
    """Download a file from URL and send it to a Telegram chat."""
    try:
        result = await send_file(
            db, user.id, chat_id, body.file_url, body.caption, body.file_name
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return SendFileResponse(**result)


@router.post("/{chat_id}/reply", response_model=SendMessageResponse)
@limiter.limit("20/minute")
async def reply_message_endpoint(
    request: Request,
    chat_id: UUID,
    body: ReplyMessageRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SendMessageResponse:
    """Reply to a specific message in a Telegram chat."""
    try:
        result = await reply_to_message(
            db, user.id, chat_id, body.telegram_message_id, body.text
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return SendMessageResponse(**result)
