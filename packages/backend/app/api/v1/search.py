import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.database import get_db
from app.core.limiter import limiter
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search_service import SearchServiceError, semantic_search

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=SearchResponse)
@limiter.limit("30/minute")
async def search_messages(
    request: Request,
    search_request: SearchRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SearchResponse:
    """Semantic search across user's Telegram messages."""
    try:
        return await semantic_search(db, user.id, search_request)
    except SearchServiceError as exc:
        logger.warning(
            "Search request failed with service unavailability",
            extra={
                "user_id": str(user.id),
                "query_length": len(search_request.query.strip()),
                "chat_filter_count": len(search_request.chat_ids or []),
                "has_date_from": search_request.date_from is not None,
                "has_date_to": search_request.date_to is not None,
                "limit": search_request.limit,
            },
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
