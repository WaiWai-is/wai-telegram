import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.single_user import (
    OwnerConfigurationError,
    is_user_active,
    validate_active_owner,
)


class TestSingleUserInvariant:
    async def test_matching_active_owner_is_valid(self, db_session, test_user):
        await validate_active_owner(db_session, test_user.id)

    async def test_mismatched_owner_is_rejected(self, db_session, test_user):
        with pytest.raises(OwnerConfigurationError, match="OWNER_USER_ID"):
            await validate_active_owner(db_session, uuid4())

    async def test_no_active_owner_is_rejected(self, db_session, test_user):
        test_user.is_active = False
        await db_session.flush()

        with pytest.raises(OwnerConfigurationError, match="OWNER_USER_ID"):
            await validate_active_owner(db_session, test_user.id)

    async def test_active_lookup_tracks_deactivation(self, db_session, test_user):
        assert await is_user_active(db_session, test_user.id) is True
        test_user.is_active = False
        await db_session.flush()
        assert await is_user_active(db_session, test_user.id) is False


async def test_single_user_validate_cli_reports_configured_owner(capsys):
    from app.cli.single_user_validate import _run

    owner_id = uuid4()

    @asynccontextmanager
    async def session_context():
        yield AsyncMock()

    with (
        patch(
            "app.cli.single_user_validate.get_settings",
            return_value=SimpleNamespace(owner_user_id=owner_id),
        ),
        patch(
            "app.cli.single_user_validate.get_session_factory",
            return_value=lambda: session_context(),
        ),
        patch(
            "app.cli.single_user_validate.validate_active_owner",
            new_callable=AsyncMock,
        ) as validate,
    ):
        await _run()

    validate.assert_awaited_once()
    assert json.loads(capsys.readouterr().out) == {
        "active_owner_valid": True,
        "owner_user_id": str(owner_id),
    }
