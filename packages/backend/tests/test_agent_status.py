"""Tests for /status command."""

import pytest

from app.services.agent.commitments import (
    Commitment,
    CommitmentDirection,
    _commitments,
    save_commitment,
)
from app.services.agent.status import _format_uptime, get_user_status
from uuid import uuid4


class TestGetUserStatus:
    def setup_method(self):
        _commitments.clear()

    @pytest.mark.asyncio
    async def test_basic_status_english(self):
        result = await get_user_status(uuid4(), user_name="Mik")
        assert "Status" in result
        assert "Mik" in result
        assert "Commitments" in result

    @pytest.mark.asyncio
    async def test_basic_status_russian(self):
        result = await get_user_status(uuid4(), user_name="Мик", user_language="ru")
        assert "Статус" in result
        assert "Мик" in result

    @pytest.mark.asyncio
    async def test_status_with_commitments(self):
        uid = uuid4()
        save_commitment(
            Commitment(
                who="me", what="send report", direction=CommitmentDirection.I_PROMISED
            ),
            uid,
        )
        save_commitment(
            Commitment(
                who="Alex",
                what="review PR",
                direction=CommitmentDirection.THEY_PROMISED,
            ),
            uid,
        )
        result = await get_user_status(uid)
        assert "1 you promised" in result
        assert "1 others promised" in result

    @pytest.mark.asyncio
    async def test_status_shows_system_info(self):
        result = await get_user_status(uuid4())
        assert "System" in result or "Система" in result
        assert "Uptime" in result or "Аптайм" in result


class TestFormatUptime:
    def test_seconds(self):
        assert _format_uptime(30) == "30s"

    def test_minutes(self):
        assert _format_uptime(150) == "2m 30s"

    def test_hours(self):
        assert _format_uptime(7200) == "2h 0m"

    def test_hours_minutes(self):
        assert _format_uptime(5430) == "1h 30m"
