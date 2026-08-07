"""Validate the production single-user invariant without mutating state."""

import asyncio
import json

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.services.single_user import validate_active_owner


async def _run() -> None:
    settings = get_settings()
    if settings.owner_user_id is None:
        raise RuntimeError("OWNER_USER_ID is required")
    async with get_session_factory()() as db:
        await validate_active_owner(db, settings.owner_user_id)
    print(
        json.dumps(
            {
                "active_owner_valid": True,
                "owner_user_id": str(settings.owner_user_id),
            }
        )
    )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
