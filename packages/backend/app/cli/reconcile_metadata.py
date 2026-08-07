import argparse
import asyncio
from uuid import UUID

from app.core.config import get_settings
from app.services.metadata_reconciliation import reconcile_owner_metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--max-messages", type=int)
    args = parser.parse_args()
    owner_user_id = get_settings().owner_user_id
    if owner_user_id is None:
        parser.error("OWNER_USER_ID is required")
    result = asyncio.run(
        reconcile_owner_metadata(
            UUID(str(owner_user_id)),
            batch_size=args.batch_size,
            max_messages=args.max_messages,
        )
    )
    print(result)


if __name__ == "__main__":
    main()
