"""Single-user ownership invariants shared by startup and background jobs."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_context
from app.models.user import User


class OwnerConfigurationError(RuntimeError):
    """Raised when database account state does not match OWNER_USER_ID."""


async def validate_active_owner(db: AsyncSession, owner_user_id: UUID) -> None:
    active_ids = list(
        (await db.execute(select(User.id).where(User.is_active.is_(True)))).scalars()
    )
    if active_ids != [owner_user_id]:
        raise OwnerConfigurationError(
            "Single-user invariant failed: exactly OWNER_USER_ID must be active"
        )


async def is_user_active(db: AsyncSession, user_id: UUID) -> bool:
    return (
        await db.execute(
            select(User.id).where(
                User.id == user_id,
                User.is_active.is_(True),
            )
        )
    ).scalar_one_or_none() is not None


async def lock_active_user(db: AsyncSession, user_id: UUID) -> bool:
    """Hold a shared row lock while a short write transaction serves the user.

    The lock prevents the single-user cutover from committing deactivation in
    the middle of a listener transaction. PostgreSQL releases it when the
    surrounding transaction commits or rolls back.
    """
    return (
        await db.execute(
            select(User.id)
            .where(
                User.id == user_id,
                User.is_active.is_(True),
            )
            .with_for_update(read=True)
        )
    ).scalar_one_or_none() is not None


async def is_user_active_in_database(user_id: UUID) -> bool:
    """Check active state in a fresh transaction for task entry points."""
    async with get_db_context() as db:
        return await is_user_active(db, user_id)
