"""Tests for the bot webhook handler — the main entry point."""

import logging

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

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
    async def test_resolution_failure_is_not_misreported_as_unknown_sender(self):
        from app.api.v1.bot_webhook import _resolve_user

        with patch(
            "app.services.agent.user_resolver.resolve_user_id",
            new=AsyncMock(side_effect=RuntimeError("database unavailable")),
        ):
            with pytest.raises(RuntimeError, match="database unavailable"):
                await _resolve_user({"id": 12345})

    @pytest.mark.asyncio
    async def test_unknown_sender_is_acknowledged_without_agent_or_reply(self):
        from app.api.v1.bot_webhook import _process_update

        update = {
            "update_id": 54321,
            "message": {
                "chat": {"id": 12345},
                "from": {"id": 99999, "first_name": "Unknown"},
                "text": "hello",
            },
        }
        with (
            patch(
                "app.api.v1.bot_webhook._resolve_user",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.v1.bot_webhook.run_agent",
                new=AsyncMock(),
            ) as run_agent,
            patch(
                "app.api.v1.bot_webhook.send_telegram_message",
                new=AsyncMock(),
            ) as send_message,
        ):
            await _process_update(update)

        run_agent.assert_not_awaited()
        send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_processing_failure_returns_503_and_remains_retryable(self):
        from app.api.v1.bot_webhook import _seen_updates, _webhook_secret
        from app.main import app

        _seen_updates.clear()
        secret = _webhook_secret()
        update = {"update_id": 99001, "message": {"chat": {"id": 123}}}
        with patch(
            "app.api.v1.bot_webhook._process_update",
            new=AsyncMock(side_effect=RuntimeError("database unavailable")),
        ) as process:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                first = await client.post(f"/api/v1/bot/webhook/{secret}", json=update)
                second = await client.post(f"/api/v1/bot/webhook/{secret}", json=update)

        assert first.status_code == 503
        assert second.status_code == 503
        assert process.await_count == 2

    @pytest.mark.asyncio
    async def test_processing_log_does_not_contain_message_or_identity_pii(
        self, caplog
    ):
        from app.api.v1.bot_webhook import _process_update

        update = {
            "message": {
                "chat": {"id": 424242},
                "from": {"id": 818181, "first_name": "PrivateName"},
                "text": "secret message body",
            }
        }
        with (
            patch(
                "app.api.v1.bot_webhook._resolve_user",
                new=AsyncMock(return_value=__import__("uuid").uuid4()),
            ),
            patch(
                "app.services.agent.rate_limit.check_rate_limit",
                return_value=False,
            ),
            patch(
                "app.api.v1.bot_webhook.send_telegram_message",
                new=AsyncMock(),
            ),
            caplog.at_level(logging.INFO),
        ):
            await _process_update(update)

        rendered = caplog.text
        assert "PrivateName" not in rendered
        assert "secret message body" not in rendered
        assert "424242" not in rendered
        assert "818181" not in rendered


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


@pytest.mark.parametrize(
    ("media_type", "payload"),
    [
        (
            "audio",
            {
                "file_id": "audio-id",
                "file_name": "recording.mp3",
                "mime_type": "audio/mpeg",
                "duration": 5,
            },
        ),
        (
            "video",
            {
                "file_id": "video-id",
                "file_name": "clip.mp4",
                "mime_type": "video/mp4",
                "duration": 6,
            },
        ),
        ("video_note", {"file_id": "note-id", "duration": 7}),
    ],
)
@pytest.mark.asyncio
async def test_direct_audio_video_and_video_note_are_processed(media_type, payload):
    from app.api.v1.bot_webhook import _process_update

    update = {
        "message": {
            "chat": {"id": 12345},
            "from": {"id": 99999, "first_name": "Owner"},
            media_type: payload,
        }
    }
    processed = __import__("types").SimpleNamespace(
        content_summary="Processed summary",
        content_text="Full transcript",
    )
    with (
        patch(
            "app.api.v1.bot_webhook._resolve_user",
            new=AsyncMock(return_value=__import__("uuid").uuid4()),
        ),
        patch(
            "app.services.agent.media_processor.process_bot_media",
            new=AsyncMock(return_value=processed),
        ) as process,
        patch(
            "app.api.v1.bot_webhook.send_telegram_message",
            new=AsyncMock(),
        ) as send,
    ):
        await _process_update(update)

    assert process.await_args.kwargs["media_type"] == media_type
    assert "Processed summary" in send.await_args.args[1]


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
