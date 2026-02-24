from fastapi import APIRouter

from app.api.v1 import auth, chats, digests, search, settings, sync, telegram

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(telegram.router, prefix="/telegram", tags=["telegram"])
api_router.include_router(chats.router, prefix="/chats", tags=["chats"])
api_router.include_router(sync.router, prefix="/sync", tags=["sync"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(digests.router, prefix="/digests", tags=["digests"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
