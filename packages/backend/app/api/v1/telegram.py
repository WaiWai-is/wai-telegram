from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient

from app.core.auth import CurrentUser
from app.core.database import get_db
from app.models.session import TelegramSession
from app.schemas.telegram import (
    RequestCodeRequest,
    RequestCodeResponse,
    SessionResponse,
    VerifyCodeRequest,
    VerifyCodeResponse,
)
from app.services import telegram_client

router = APIRouter()

# Temporary storage for auth clients (in production, use Redis)
_auth_clients: dict[str, TelegramClient] = {}


@router.post("/request-code", response_model=RequestCodeResponse)
async def request_code(
    request: RequestCodeRequest,
    user: CurrentUser,
) -> RequestCodeResponse:
    """Request verification code for Telegram authentication."""
    try:
        client, phone_code_hash = await telegram_client.request_code(request.phone_number)
        # Store client temporarily
        _auth_clients[f"{user.id}:{request.phone_number}"] = client
        return RequestCodeResponse(phone_code_hash=phone_code_hash)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/verify-code", response_model=VerifyCodeResponse)
async def verify_code(
    request: VerifyCodeRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VerifyCodeResponse:
    """Verify code and complete Telegram authentication."""
    client_key = f"{user.id}:{request.phone_number}"
    client = _auth_clients.get(client_key)

    if not client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending authentication. Request a code first.",
        )

    try:
        session_string, telegram_user_id = await telegram_client.verify_code(
            client,
            request.phone_number,
            request.phone_code_hash,
            request.code,
            request.password,
        )

        # Save session
        await telegram_client.save_session(
            db,
            user.id,
            request.phone_number,
            session_string,
            telegram_user_id,
        )

        # Clean up temporary client
        del _auth_clients[client_key]

        return VerifyCodeResponse(
            success=True,
            telegram_user_id=telegram_user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/session", response_model=SessionResponse | None)
async def get_session(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionResponse | None:
    """Get current Telegram session info."""
    result = await db.execute(
        select(TelegramSession).where(
            TelegramSession.user_id == user.id,
            TelegramSession.is_active == True,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None
    return SessionResponse.model_validate(session)


@router.delete("/session")
async def delete_session(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Delete Telegram session (logout)."""
    await telegram_client.delete_session(db, user.id)
    return {"message": "Session deleted successfully"}
