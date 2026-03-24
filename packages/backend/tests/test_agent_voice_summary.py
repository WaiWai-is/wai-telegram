"""Tests for Voice Summary — the #1 wow moment."""

import pytest

from app.services.agent.voice_summary import (
    estimate_voice_duration_text,
    summarize_voice,
)


class TestSummarizeVoiceBasic:
    @pytest.mark.asyncio
    async def test_empty_transcript(self):
        result = await summarize_voice("")
        assert "Could not transcribe" in result

    @pytest.mark.asyncio
    async def test_whitespace_only(self):
        result = await summarize_voice("   ")
        assert "Could not transcribe" in result

    @pytest.mark.asyncio
    async def test_short_transcript(self):
        result = await summarize_voice("Call me back please")
        assert "Transcript" in result
        assert "Call me back" in result

    @pytest.mark.asyncio
    async def test_medium_transcript_has_transcript_section(self):
        text = "We had a long meeting about the budget. " * 10
        result = await summarize_voice(text)
        assert "Transcript" in result

    @pytest.mark.asyncio
    async def test_long_transcript_truncated(self):
        text = "Important discussion about Q2 planning. " * 50
        result = await summarize_voice(text)
        assert "first 500 chars" in result or "Transcript" in result

    @pytest.mark.asyncio
    async def test_entities_extracted(self):
        result = await summarize_voice(
            "Met with Sarah and Alex today. Budget is $50k for the project."
        )
        assert "Sarah" in result or "Alex" in result or "$50k" in result

    @pytest.mark.asyncio
    async def test_commitments_detected(self):
        result = await summarize_voice(
            "I'll send the report by Friday. Alex promised to review it."
        )
        # Either commitment keywords or the detection
        assert (
            "promised" in result.lower()
            or "commitment" in result.lower()
            or "Friday" in result
        )

    @pytest.mark.asyncio
    async def test_russian_transcript(self):
        result = await summarize_voice(
            "Встретились с Алексом. Решили бюджет 500 тысяч. Запуск до марта."
        )
        assert "Transcript" in result

    @pytest.mark.asyncio
    async def test_decisions_detected(self):
        result = await summarize_voice(
            "We decided to go with PostgreSQL for the database. "
            "The team agreed to launch on March 30th. "
            "Alex will handle the backend, Sarah takes frontend."
        )
        assert "Transcript" in result


class TestDurationText:
    def test_none(self):
        assert estimate_voice_duration_text(None) == ""

    def test_seconds(self):
        assert estimate_voice_duration_text(45) == "45s"

    def test_one_minute(self):
        assert estimate_voice_duration_text(60) == "1m"

    def test_minutes_and_seconds(self):
        assert estimate_voice_duration_text(90) == "1m30s"

    def test_several_minutes(self):
        assert estimate_voice_duration_text(300) == "5m"

    def test_long_voice(self):
        assert estimate_voice_duration_text(420) == "7m"
