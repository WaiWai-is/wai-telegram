import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
from app.core.limiter import limiter
from app.services import telegram_client

logger = logging.getLogger(__name__)
router = APIRouter()

# Auth clients with TTL tracking: key -> (client, created_timestamp)
MAX_AUTH_CLIENTS = 50
_auth_clients: dict[str, tuple[TelegramClient, float]] = {}
_AUTH_CLIENT_TTL = 300  # 5 minutes


async def _cleanup_expired_auth_clients() -> None:
    """Remove auth clients older than TTL, with proper async disconnect."""
    now = time.time()
    expired = [k for k, (_, ts) in _auth_clients.items() if now - ts > _AUTH_CLIENT_TTL]
    for key in expired:
        client, _ = _auth_clients.pop(key)
        logger.info(f"Cleaned up expired auth client: {key}")
        try:
            await client.disconnect()
        except Exception:
            pass

    # Enforce max limit — evict oldest if over cap
    if len(_auth_clients) > MAX_AUTH_CLIENTS:
        sorted_keys = sorted(_auth_clients, key=lambda k: _auth_clients[k][1])
        for key in sorted_keys[:len(_auth_clients) - MAX_AUTH_CLIENTS]:
            client, _ = _auth_clients.pop(key)
            logger.info(f"Evicted auth client (over limit): {key}")
            try:
                await client.disconnect()
            except Exception:
                pass


@router.post("/request-code", response_model=RequestCodeResponse)
@limiter.limit("3/minute")
async def request_code(
    request: Request,
    body: RequestCodeRequest,
    user: CurrentUser,
) -> RequestCodeResponse:
    """Request verification code for Telegram authentication."""
    await _cleanup_expired_auth_clients()
    try:
        client, phone_code_hash, code_type = await telegram_client.request_code(
            body.phone_number
        )
        _auth_clients[f"{user.id}:{body.phone_number}"] = (client, time.time())
        return RequestCodeResponse(
            phone_code_hash=phone_code_hash,
            code_type=code_type,
        )
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
    await _cleanup_expired_auth_clients()
    client_key = f"{user.id}:{request.phone_number}"
    entry = _auth_clients.get(client_key)

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending authentication. Request a code first.",
        )
    client, _ = entry

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
