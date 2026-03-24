"""Tests for the bot webhook handler — the main entry point."""

import pytest
from httpx import ASGITransport, AsyncClient

# Need to set env before importing app
import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token-for-testing")


class TestWebhookSecurity:
    """Test webhook secret validation."""

    @pytest.mark.asyncio
    async def test_wrong_secret_returns_403(self):
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/bot/webhook/wrong-secret",
                json={"update_id": 1},
            )
            assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(self):
        from app.api.v1.bot_webhook import _webhook_secret
        from app.main import app

        secret = _webhook_secret()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/v1/bot/webhook/{secret}",
                content=b"not json",
                headers={"content-type": "application/json"},
            )
            assert resp.status_code == 400


class TestLanguageDetection:
    """Test the _detect_language helper."""

    def test_english_text(self):
        from app.api.v1.bot_webhook import _detect_language

        assert _detect_language("Hello world") == "en"

    def test_russian_text(self):
        from app.api.v1.bot_webhook import _detect_language

        assert _detect_language("Привет мир") == "ru"

    def test_empty_text(self):
        from app.api.v1.bot_webhook import _detect_language

        assert _detect_language("") == "en"


class TestResolveUser:
    """Test the user resolution helper."""

    @pytest.mark.asyncio
    async def test_returns_uuid(self):
        from uuid import UUID

        from app.api.v1.bot_webhook import _resolve_user

        # Without DB, falls back to placeholder
        result = await _resolve_user({"id": 12345})
        assert isinstance(result, UUID)


class TestRateLimiting:
    """Test rate limiting integration."""

    def test_normal_usage_allowed(self):
        from app.services.agent.rate_limit import check_rate_limit, clear_rate_limits

        clear_rate_limits()
        assert check_rate_limit(99999) is True

    def test_abuse_blocked(self):
        from app.services.agent.rate_limit import (
            MINUTE_LIMIT,
            check_rate_limit,
            clear_rate_limits,
        )

        clear_rate_limits()
        for _ in range(MINUTE_LIMIT):
            check_rate_limit(88888)
        assert check_rate_limit(88888) is False


class TestBotTokenHelper:
    """Test _get_bot_token."""

    def test_reads_from_env(self):
        from app.api.v1.bot_webhook import _get_bot_token

        token = _get_bot_token()
        assert token  # Should be non-empty (from env or settings)

    def test_webhook_secret_deterministic(self):
        from app.api.v1.bot_webhook import _webhook_secret

        s1 = _webhook_secret()
        s2 = _webhook_secret()
        assert s1 == s2
        assert len(s1) == 32
