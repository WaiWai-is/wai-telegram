import asyncio
import logging
from datetime import date, timedelta
from uuid import UUID

from celery import group, shared_task
from sqlalchemy import select

from app.core.database import get_db_context
from app.models.user import User
from app.services.digest_service import generate_digest

logger = logging.getLogger(__name__)


@shared_task
def generate_all_digests():
    """Dispatch per-user digest tasks in parallel using Celery group."""
    result = asyncio.run(_get_user_ids())
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    if not result:
        return {"date": yesterday, "users_processed": 0, "dispatched": 0}

    # Dispatch all user digests in parallel
    job = group(
        generate_user_digest.s(str(uid), yesterday) for uid in result
    )
    job.apply_async()

    return {
        "date": yesterday,
        "users_processed": len(result),
        "dispatched": len(result),
    }


async def _get_user_ids() -> list[UUID]:
    """Get all user IDs for digest generation."""
    async with get_db_context() as db:
        result = await db.execute(select(User.id))
        return list(result.scalars().all())


@shared_task
def generate_user_digest(user_id: str, digest_date: str | None = None):
    """Generate digest for a specific user."""
    return asyncio.run(
        _generate_user_digest(UUID(user_id), digest_date)
    )


async def _generate_user_digest(user_id: UUID, digest_date: str | None) -> dict:
    """Generate digest for a user."""
    target_date = date.fromisoformat(digest_date) if digest_date else None

    async with get_db_context() as db:
        digest = await generate_digest(db, user_id, target_date)
        return {
            "digest_id": str(digest.id),
            "date": digest.digest_date.isoformat(),
        }
