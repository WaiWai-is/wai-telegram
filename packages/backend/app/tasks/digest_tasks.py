import asyncio
import logging
from datetime import date, timedelta
from uuid import UUID

from celery import shared_task
from sqlalchemy import select

from app.core.database import get_db_context
from app.models.user import User
from app.services.digest_service import generate_digest

logger = logging.getLogger(__name__)


@shared_task
def generate_all_digests():
    """Generate daily digests for all users."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(_generate_all_digests())
        return result
    finally:
        loop.close()


async def _generate_all_digests() -> dict:
    """Generate digests for all users."""
    yesterday = date.today() - timedelta(days=1)
    generated = 0
    errors = 0

    async with get_db_context() as db:
        result = await db.execute(select(User))
        users = result.scalars().all()

        for user in users:
            try:
                await generate_digest(db, user.id, yesterday)
                generated += 1
                logger.info(f"Generated digest for user {user.id}")
            except Exception as e:
                errors += 1
                logger.error(f"Failed to generate digest for user {user.id}: {e}")

    return {
        "date": yesterday.isoformat(),
        "users_processed": len(users),
        "generated": generated,
        "errors": errors,
    }


@shared_task
def generate_user_digest(user_id: str, digest_date: str | None = None):
    """Generate digest for a specific user."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            _generate_user_digest(UUID(user_id), digest_date)
        )
        return result
    finally:
        loop.close()


async def _generate_user_digest(user_id: UUID, digest_date: str | None) -> dict:
    """Generate digest for a user."""
    target_date = date.fromisoformat(digest_date) if digest_date else None

    async with get_db_context() as db:
        digest = await generate_digest(db, user_id, target_date)
        return {
            "digest_id": str(digest.id),
            "date": digest.digest_date.isoformat(),
        }
