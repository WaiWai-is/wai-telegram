from unittest.mock import AsyncMock, patch

import pytest
from app.services.bot_service import _split_message, send_telegram_message


class TestSplitMessage:
    def test_short_message_no_split(self):
        result = _split_message("Hello world")
        assert result == ["Hello world"]

    def test_exact_limit_no_split(self):
        text = "a" * 4096
        result = _split_message(text)
        assert result == [text]

    def test_split_at_newline(self):
        text = "a" * 4000 + "\n" + "b" * 200
        result = _split_message(text, max_length=4096)
        assert len(result) == 2
        assert result[0] == "a" * 4000
        assert result[1] == "b" * 200

    def test_split_no_newline(self):
        text = "a" * 5000
        result = _split_message(text, max_length=4096)
        assert len(result) == 2
        assert result[0] == "a" * 4096
        assert result[1] == "a" * 904

    def test_multi_chunk_split(self):
        text = "a" * 10000
        result = _split_message(text, max_length=4096)
        assert len(result) == 3
        assert "".join(result) == text

    def test_empty_string(self):
        result = _split_message("")
        assert result == [""]


class TestSendTelegramMessage:
    async def test_send_success(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch("app.services.bot_service.settings") as mock_settings:
            mock_settings.telegram_bot_token = "bot-token"
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                await send_telegram_message(12345, "Hello")
                mock_client.post.assert_called_once()

    async def test_send_no_token_raises(self):
        with patch("app.services.bot_service.settings") as mock_settings:
            mock_settings.telegram_bot_token = ""
            with pytest.raises(ValueError, match="not configured"):
                await send_telegram_message(12345, "Hello")

    async def test_send_http_error_does_not_leak_token(self):
        """A failing send must raise without exposing the bot token."""
        token = "8759392549:AAGhrnMPOI0rijnXQswljKGMkSCXWxYP_HA"
        mock_response = AsyncMock()
        mock_response.status_code = 401
        mock_response.text = (
            '{"ok":false,"error_code":401,"description":"Unauthorized"}'
        )

        with patch("app.services.bot_service.settings") as mock_settings:
            mock_settings.telegram_bot_token = token
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                with pytest.raises(RuntimeError) as exc_info:
                    await send_telegram_message(12345, "Hello")

        assert token not in str(exc_info.value)
        assert "401" in str(exc_info.value)
