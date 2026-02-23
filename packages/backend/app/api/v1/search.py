from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.database import get_db
from app.core.limiter import limiter
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search_service import semantic_search

router = APIRouter()


@router.post("", response_model=SearchResponse)
@limiter.limit("30/minute")
async def search_messages(
    request: Request,
    search_request: SearchRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SearchResponse:
    """Semantic search across user's Telegram messages."""
    return await semantic_search(db, user.id, search_request)
