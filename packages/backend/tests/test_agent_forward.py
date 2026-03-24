"""Tests for Forward Processor — the second brain mechanic."""

import pytest

from app.services.agent.commitments import _commitments
from app.services.agent.forward_processor import (
    is_forwarded_message,
    parse_forwarded_message,
    process_forwarded_message,
)


class TestIsForwarded:
    def test_forwarded_from_user(self):
        msg = {"forward_from": {"id": 123, "first_name": "Alex"}}
        assert is_forwarded_message(msg) is True

    def test_forwarded_from_chat(self):
        msg = {"forward_from_chat": {"id": -100123, "title": "Tech News"}}
        assert is_forwarded_message(msg) is True

    def test_forwarded_sender_name(self):
        msg = {"forward_sender_name": "Hidden User"}
        assert is_forwarded_message(msg) is True

    def test_forwarded_date_only(self):
        msg = {"forward_date": 1711400000}
        assert is_forwarded_message(msg) is True

    def test_not_forwarded(self):
        msg = {"text": "Hello", "from": {"id": 123}}
        assert is_forwarded_message(msg) is False

    def test_empty_message(self):
        assert is_forwarded_message({}) is False


class TestParseForwarded:
    def test_text_message(self):
        msg = {
            "text": "Hello world",
            "forward_from": {"first_name": "Alex", "last_name": "Smith"},
            "forward_date": 1711400000,
        }
        content = parse_forwarded_message(msg)
        assert content.text == "Hello world"
        assert content.content_type == "text"
        assert content.source_sender == "Alex Smith"

    def test_voice_message(self):
        msg = {"voice": {"file_id": "abc123"}, "forward_from": {"first_name": "Maria"}}
        content = parse_forwarded_message(msg)
        assert content.content_type == "voice"
        assert content.source_sender == "Maria"

    def test_photo_message(self):
        msg = {"photo": [{"file_id": "abc"}], "caption": "Nice view!"}
        content = parse_forwarded_message(msg)
        assert content.content_type == "photo"
        assert content.text == "Nice view!"

    def test_document_message(self):
        msg = {"document": {"file_id": "abc", "file_name": "report.pdf"}}
        content = parse_forwarded_message(msg)
        assert content.content_type == "document"

    def test_url_detection(self):
        msg = {"text": "Check this out https://example.com/article"}
        content = parse_forwarded_message(msg)
        assert content.has_url is True
        assert content.url == "https://example.com/article"

    def test_no_url(self):
        msg = {"text": "No links here"}
        content = parse_forwarded_message(msg)
        assert content.has_url is False

    def test_forward_from_channel(self):
        msg = {
            "text": "Breaking news!",
            "forward_from_chat": {"id": -100123, "title": "CNN Breaking"},
        }
        content = parse_forwarded_message(msg)
        assert content.source_chat == "CNN Breaking"


class TestProcessForwarded:
    def setup_method(self):
        _commitments.clear()

    @pytest.mark.asyncio
    async def test_text_saved(self):
        msg = {
            "text": "Budget meeting notes: we decided on $50k for Q2",
            "forward_from": {"first_name": "Alex"},
            "forward_date": 1711400000,
        }
        result = await process_forwarded_message(msg)
        assert "Saved" in result
        assert "Alex" in result
        assert "Remembered" in result

    @pytest.mark.asyncio
    async def test_entities_extracted(self):
        msg = {
            "text": "Met with Sarah. Budget $50k. Launch March 30.",
            "forward_from": {"first_name": "Team"},
        }
        result = await process_forwarded_message(msg)
        assert "Sarah" in result or "$50k" in result or "50k" in result

    @pytest.mark.asyncio
    async def test_commitments_detected(self):
        msg = {
            "text": "I'll send the contract by Friday",
            "forward_from": {"first_name": "Alex"},
        }
        result = await process_forwarded_message(msg, user_name="Mik")
        assert (
            "Commitment" in result or "promise" in result.lower() or "Friday" in result
        )

    @pytest.mark.asyncio
    async def test_url_shown(self):
        msg = {
            "text": "Great article https://example.com/ai-news",
            "forward_from": {"first_name": "Bob"},
        }
        result = await process_forwarded_message(msg)
        assert "https://example.com/ai-news" in result
        assert "🔗" in result

    @pytest.mark.asyncio
    async def test_voice_forward(self):
        msg = {"voice": {"file_id": "abc"}, "forward_from": {"first_name": "Maria"}}
        result = await process_forwarded_message(msg)
        assert "Voice" in result or "🎤" in result

    @pytest.mark.asyncio
    async def test_photo_forward(self):
        msg = {"photo": [{"file_id": "abc"}], "forward_from": {"first_name": "Team"}}
        result = await process_forwarded_message(msg)
        assert "Photo" in result or "📷" in result

    @pytest.mark.asyncio
    async def test_document_forward(self):
        msg = {
            "document": {"file_id": "abc", "file_name": "report.pdf"},
            "forward_from": {"first_name": "HR"},
        }
        result = await process_forwarded_message(msg)
        assert "report.pdf" in result

    @pytest.mark.asyncio
    async def test_long_text_truncated(self):
        msg = {
            "text": "A" * 500,
            "forward_from": {"first_name": "X"},
        }
        result = await process_forwarded_message(msg)
        assert "..." in result
