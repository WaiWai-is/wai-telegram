"""Tests for typing indicator module."""

import pytest
from unittest.mock import AsyncMock, patch


class TestSendTypingAction:
    @pytest.mark.asyncio
    async def test_no_token_does_nothing(self):
        """No token → silently returns (no crash)."""
        with (
            patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": ""}, clear=False),
            patch("app.services.agent.typing.get_settings") as mock_settings,
        ):
            mock_settings.return_value.telegram_bot_token = ""
            from app.services.agent.typing import send_typing_action

            # Should not raise
            await send_typing_action(12345)

    @pytest.mark.asyncio
    async def test_with_token_calls_api(self):
        """With token → calls Telegram API."""
        with patch.dict(
            "os.environ", {"TELEGRAM_BOT_TOKEN": "test-token"}, clear=False
        ):
            with patch(
                "app.services.agent.typing.httpx.AsyncClient"
            ) as mock_client_cls:
                mock_client = AsyncMock()
                mock_client_cls.return_value.__aenter__ = AsyncMock(
                    return_value=mock_client
                )
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock()

                from app.services.agent.typing import send_typing_action

                await send_typing_action(12345)
                mock_client.post.assert_called_once()
                call_args = mock_client.post.call_args
                assert "sendChatAction" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_api_failure_doesnt_crash(self):
        """API failure → logged, no crash."""
        with patch.dict(
            "os.environ", {"TELEGRAM_BOT_TOKEN": "test-token"}, clear=False
        ):
            with patch(
                "app.services.agent.typing.httpx.AsyncClient"
            ) as mock_client_cls:
                mock_client = AsyncMock()
                mock_client_cls.return_value.__aenter__ = AsyncMock(
                    return_value=mock_client
                )
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(side_effect=Exception("Network error"))

                from app.services.agent.typing import send_typing_action

                # Should not raise
                await send_typing_action(12345)
