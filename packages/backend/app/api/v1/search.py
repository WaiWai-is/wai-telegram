from typing import Annotated

from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.database import get_db
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search_service import semantic_search

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("", response_model=SearchResponse)
@limiter.limit("30/minute")
async def search_messages(
    request_obj: Request,
    search_request: SearchRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SearchResponse:
    """Semantic search across user's Telegram messages."""
    return await semantic_search(db, user.id, search_request)
