import json
import logging
from typing import Annotated

import redis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.config import get_settings
from app.core.database import get_db
from app.models.session import TelegramSession
from app.models.settings import UserSettings
from app.schemas.settings import (
    TestBotResponse,
    UserSettingsResponse,
    UserSettingsUpdate,
)
from app.services.bot_service import send_telegram_message

logger = logging.getLogger(__name__)
router = APIRouter()
config = get_settings()
_redis = redis.from_url(config.redis_url)


async def _get_or_create_settings(db: AsyncSession, user_id) -> UserSettings:
    """Get user settings, creating defaults if they don't exist."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    if not settings:
        settings = UserSettings(user_id=user_id)
        db.add(settings)
        await db.flush()
    return settings


@router.get("", response_model=UserSettingsResponse)
async def get_settings_endpoint(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserSettingsResponse:
    """Get user settings."""
    settings = await _get_or_create_settings(db, user.id)
    listener_active = bool(_redis.get(f"listener:active:{user.id}"))
    return UserSettingsResponse(
        digest_enabled=settings.digest_enabled,
        digest_hour_utc=settings.digest_hour_utc,
        digest_timezone=settings.digest_timezone,
        digest_telegram_enabled=settings.digest_telegram_enabled,
        realtime_sync_enabled=settings.realtime_sync_enabled,
        listener_active=listener_active,
    )


@router.put("", response_model=UserSettingsResponse)
async def update_settings(
    body: UserSettingsUpdate,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserSettingsResponse:
    """Update user settings (partial update)."""
    settings = await _get_or_create_settings(db, user.id)

    updates = body.model_dump(exclude_unset=True)

    # Track if realtime changed
    realtime_changed = (
        "realtime_sync_enabled" in updates
        and updates["realtime_sync_enabled"] != settings.realtime_sync_enabled
    )
    new_realtime_value = updates.get("realtime_sync_enabled")

    for field, value in updates.items():
        setattr(settings, field, value)

    await db.flush()

    # Notify listener service about realtime toggle
    if realtime_changed:
        command = "start_user" if new_realtime_value else "stop_user"
        _redis.publish(
            "listener:cmd:global",
            json.dumps({"command": command, "user_id": str(user.id)}),
        )

    listener_active = bool(_redis.get(f"listener:active:{user.id}"))
    return UserSettingsResponse(
        digest_enabled=settings.digest_enabled,
        digest_hour_utc=settings.digest_hour_utc,
        digest_timezone=settings.digest_timezone,
        digest_telegram_enabled=settings.digest_telegram_enabled,
        realtime_sync_enabled=settings.realtime_sync_enabled,
        listener_active=listener_active,
    )


@router.post("/test-bot", response_model=TestBotResponse)
async def test_bot(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TestBotResponse:
    """Send a test message via the Telegram bot."""
    if not config.telegram_bot_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bot token not configured",
        )

    # Get user's Telegram user ID
    result = await db.execute(
        select(TelegramSession).where(
            TelegramSession.user_id == user.id,
            TelegramSession.is_active == True,  # noqa: E712
        )
    )
    session = result.scalar_one_or_none()
    if not session or not session.telegram_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Telegram session found. Connect Telegram first.",
        )

    await send_telegram_message(
        session.telegram_user_id,
        "This is a test message from WAI Telegram AI. If you see this, bot delivery is working!",
    )
    return TestBotResponse(success=True, message="Test message sent successfully")
