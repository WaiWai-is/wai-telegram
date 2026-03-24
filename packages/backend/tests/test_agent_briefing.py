"""Tests for Morning Briefing — Wai comes to you."""

from uuid import uuid4

import pytest

from app.services.agent.briefing import (
    _russian_day_name,
    generate_morning_briefing,
    should_send_briefing,
)
from app.services.agent.commitments import (
    Commitment,
    CommitmentDirection,
    _commitments,
    save_commitment,
)


class TestMorningBriefing:
    def setup_method(self):
        _commitments.clear()

    @pytest.mark.asyncio
    async def test_empty_briefing_returns_none(self):
        """[no_message] pattern: nothing to report → stay silent."""
        result = await generate_morning_briefing(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_briefing_with_commitments(self):
        user_id = uuid4()
        save_commitment(
            Commitment(
                who="me",
                what="send report",
                direction=CommitmentDirection.I_PROMISED,
                deadline="Friday",
            ),
            user_id,
        )
        result = await generate_morning_briefing(user_id)
        assert result is not None
        assert "Good morning" in result
        assert "send report" in result
        assert "Friday" in result

    @pytest.mark.asyncio
    async def test_briefing_russian(self):
        user_id = uuid4()
        save_commitment(
            Commitment(
                who="me",
                what="отправить отчёт",
                direction=CommitmentDirection.I_PROMISED,
            ),
            user_id,
        )
        result = await generate_morning_briefing(
            user_id, user_name="Mik", user_language="ru"
        )
        assert result is not None
        assert "Доброе утро" in result
        assert "Mik" in result
        assert "отправить отчёт" in result

    @pytest.mark.asyncio
    async def test_briefing_with_they_promised(self):
        user_id = uuid4()
        save_commitment(
            Commitment(
                who="Alex",
                what="send contract",
                direction=CommitmentDirection.THEY_PROMISED,
                deadline="Monday",
            ),
            user_id,
        )
        result = await generate_morning_briefing(user_id)
        assert result is not None
        assert "Alex" in result
        assert "send contract" in result

    @pytest.mark.asyncio
    async def test_briefing_with_user_name(self):
        user_id = uuid4()
        save_commitment(
            Commitment(who="me", what="task", direction=CommitmentDirection.I_PROMISED),
            user_id,
        )
        result = await generate_morning_briefing(user_id, user_name="Sarah")
        assert "Sarah" in result

    @pytest.mark.asyncio
    async def test_briefing_has_date(self):
        user_id = uuid4()
        save_commitment(
            Commitment(who="me", what="task", direction=CommitmentDirection.I_PROMISED),
            user_id,
        )
        result = await generate_morning_briefing(user_id)
        assert result is not None
        # Should contain some date format
        assert "202" in result  # Year


class TestShouldSendBriefing:
    def setup_method(self):
        _commitments.clear()

    @pytest.mark.asyncio
    async def test_no_commitments_no_briefing(self):
        assert await should_send_briefing(uuid4()) is False

    @pytest.mark.asyncio
    async def test_with_commitments_send_briefing(self):
        user_id = uuid4()
        save_commitment(
            Commitment(who="me", what="task", direction=CommitmentDirection.I_PROMISED),
            user_id,
        )
        assert await should_send_briefing(user_id) is True


class TestRussianDayNames:
    def test_monday(self):
        assert _russian_day_name(0) == "Понедельник"

    def test_friday(self):
        assert _russian_day_name(4) == "Пятница"

    def test_sunday(self):
        assert _russian_day_name(6) == "Воскресенье"

    def test_invalid(self):
        assert _russian_day_name(7) == ""
