import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from celery import group, shared_task
from sqlalchemy import or_, select
from sqlalchemy.sql import and_

from app.core.database import get_db_context
from app.models.session import TelegramSession
from app.models.settings import UserSettings
from app.models.user import User
from app.services.bot_service import send_telegram_message
from app.services.digest_service import generate_digest

logger = logging.getLogger(__name__)


@shared_task
def generate_all_digests():
    """Dispatch per-user digest tasks for users whose digest_hour_utc matches now."""
    current_hour = datetime.now(UTC).hour
    result = asyncio.run(_get_eligible_user_ids(current_hour))
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    if not result:
        return {
            "date": yesterday,
            "hour": current_hour,
            "users_processed": 0,
            "dispatched": 0,
        }

    # Dispatch all user digests in parallel
    job = group(generate_user_digest.s(str(uid), yesterday) for uid in result)
    job.apply_async()

    return {
        "date": yesterday,
        "hour": current_hour,
        "users_processed": len(result),
        "dispatched": len(result),
    }


async def _get_eligible_user_ids(current_hour: int) -> list[UUID]:
    """Get user IDs eligible for digest generation at the current hour."""
    async with get_db_context() as db:
        # Users with settings: check digest_enabled and hour match
        # Users without settings row use defaults (enabled=True, hour=9)
        conditions = [
            and_(
                UserSettings.digest_enabled == True,
                UserSettings.digest_hour_utc == current_hour,
            )
        ]
        if current_hour == 9:
            conditions.append(UserSettings.id.is_(None))

        result = await db.execute(
            select(User.id)
            .outerjoin(UserSettings, User.id == UserSettings.user_id)
            .where(or_(*conditions))
        )
        return list(result.scalars().all())


@shared_task
def generate_user_digest(user_id: str, digest_date: str | None = None):
    """Generate digest for a specific user."""
    return asyncio.run(_generate_user_digest(UUID(user_id), digest_date))


async def _generate_user_digest(user_id: UUID, digest_date: str | None) -> dict:
    """Generate digest for a user, optionally sending via Telegram bot."""
    target_date = date.fromisoformat(digest_date) if digest_date else None

    async with get_db_context() as db:
        digest = await generate_digest(db, user_id, target_date)

        # Check if user wants Telegram bot delivery
        result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()

        if settings and settings.digest_telegram_enabled:
            # Get telegram_user_id from session
            result = await db.execute(
                select(TelegramSession).where(
                    TelegramSession.user_id == user_id,
                    TelegramSession.is_active == True,
                )
            )
            session = result.scalar_one_or_none()

            if session and session.telegram_user_id:
                try:
                    await send_telegram_message(
                        session.telegram_user_id,
                        f"*Daily Digest — {digest.digest_date}*\n\n{digest.content}",
                    )
                    logger.info(f"Sent digest to Telegram for user {user_id}")
                except Exception as e:
                    logger.error(
                        f"Failed to send digest to Telegram for user {user_id}: {e}"
                    )

        return {
            "digest_id": str(digest.id),
            "date": digest.digest_date.isoformat(),
        }
