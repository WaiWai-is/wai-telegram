from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, RequireWrite
from app.core.database import get_db
from app.core.limiter import limiter
from app.schemas.digest import DigestGenerateRequest, DigestResponse
from app.services.digest_service import generate_digest, get_digest, get_digests

router = APIRouter()


@router.get("", response_model=list[DigestResponse])
async def list_digests(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=30, ge=1, le=100),
) -> list[DigestResponse]:
    """List user's daily digests."""
    digests = await get_digests(db, user.id, limit)
    return [DigestResponse.model_validate(d) for d in digests]


@router.get("/{digest_date}", response_model=DigestResponse)
async def get_digest_by_date(
    digest_date: date,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DigestResponse:
    """Get digest for a specific date."""
    digest = await get_digest(db, user.id, digest_date)
    if not digest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Digest not found for this date",
        )
    return DigestResponse.model_validate(digest)


@router.post("/generate", response_model=DigestResponse)
@limiter.limit("5/hour")
async def generate_daily_digest(
    request: Request,
    ctx: RequireWrite,
    db: Annotated[AsyncSession, Depends(get_db)],
    body: DigestGenerateRequest | None = None,
) -> DigestResponse:
    """Generate digest for a specific date (defaults to yesterday)."""
    digest_date = body.date if body else None
    digest = await generate_digest(db, ctx.user.id, digest_date)
    return DigestResponse.model_validate(digest)
