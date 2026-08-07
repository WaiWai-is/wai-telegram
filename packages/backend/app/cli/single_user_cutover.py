"""Dry-run and apply the evidence-gated production single-user cutover."""

import argparse
import asyncio
import json
from dataclasses import asdict
from uuid import UUID

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.services.single_user import validate_active_owner
from app.services.single_user_cutover import (
    apply_single_user_cutover,
    collect_archived_session_credentials,
    collect_owner_evidence,
    purge_deactivated_runtime_state,
    revoke_archived_telegram_sessions,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm-owner",
        type=UUID,
        help="Required with --apply; must exactly match OWNER_USER_ID.",
    )
    parser.add_argument("--recent-key-minutes", type=int, default=60)
    return parser


async def _run(args: argparse.Namespace) -> None:
    from datetime import timedelta

    settings = get_settings()
    owner_user_id = settings.owner_user_id
    if owner_user_id is None:
        raise RuntimeError("OWNER_USER_ID is required")
    if args.apply and args.confirm_owner != owner_user_id:
        raise RuntimeError("--confirm-owner must exactly match OWNER_USER_ID")

    session_factory = get_session_factory()
    async with session_factory() as db:
        evidence = await collect_owner_evidence(
            db,
            expected_owner_user_id=owner_user_id,
            recent_key_window=timedelta(minutes=args.recent_key_minutes),
        )
        credentials = await collect_archived_session_credentials(db, owner_user_id)

    preview = evidence.public_dict()
    preview["archived_session_credentials_to_revoke"] = len(credentials)
    preview["mode"] = "apply" if args.apply else "dry-run"
    print(json.dumps(preview, sort_keys=True))
    if not args.apply:
        return

    # The evidence above is the final read before any irreversible external
    # mutation. A failure below is explicit and the command remains rerunnable;
    # no database credentials are erased until all revocations succeed.
    revoked_sessions = await revoke_archived_telegram_sessions(credentials)

    async with session_factory() as db:
        result = await apply_single_user_cutover(db, evidence)
        await db.commit()

    async with session_factory() as db:
        await validate_active_owner(db, owner_user_id)

    redis_keys_deleted = await _purge_runtime_state_with_retries(
        settings.redis_url, result
    )
    output = asdict(result)
    for key in ("owner_user_id", "cancelled_job_ids", "deactivated_user_ids"):
        value = output[key]
        output[key] = (
            [str(item) for item in value] if isinstance(value, tuple) else str(value)
        )
    output["telegram_authorizations_revoked"] = revoked_sessions
    output["redis_keys_deleted"] = redis_keys_deleted
    output["mode"] = "applied"
    print(json.dumps(output, sort_keys=True))


async def _purge_runtime_state_with_retries(redis_url: str, result) -> int:
    last_error: Exception | None = None
    for delay in (0, 1, 5):
        if delay:
            await asyncio.sleep(delay)
        try:
            return await purge_deactivated_runtime_state(redis_url, result)
        except Exception as error:
            last_error = error
    raise RuntimeError(
        "Database cutover committed, but Redis runtime-state purge failed after "
        "three attempts; keep services stopped and rerun the purge"
    ) from last_error


def main() -> None:
    asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    main()
