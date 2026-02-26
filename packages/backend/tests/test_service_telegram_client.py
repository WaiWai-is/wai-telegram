from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.telegram_client import (
    _get_code_type_name,
    request_code,
    verify_code,
)


class TestGetCodeTypeName:
    def test_app_type(self):
        sent_code = MagicMock()
        sent_code.type = MagicMock()
        type(sent_code.type).__name__ = "SentCodeTypeApp"
        assert _get_code_type_name(sent_code) == "app"

    def test_sms_type(self):
        sent_code = MagicMock()
        sent_code.type = MagicMock()
        type(sent_code.type).__name__ = "SentCodeTypeSms"
        assert _get_code_type_name(sent_code) == "sms"

    def test_call_type(self):
        sent_code = MagicMock()
        sent_code.type = MagicMock()
        type(sent_code.type).__name__ = "SentCodeTypeCall"
        assert _get_code_type_name(sent_code) == "call"

    def test_unknown_type(self):
        sent_code = MagicMock()
        sent_code.type = MagicMock()
        type(sent_code.type).__name__ = "SomethingNew"
        assert _get_code_type_name(sent_code) == "unknown"


class TestRequestCode:
    async def test_success(self):
        mock_client = AsyncMock()
        mock_result = MagicMock()
        mock_result.phone_code_hash = "hash123"
        mock_result.type = MagicMock()
        type(mock_result.type).__name__ = "SentCodeTypeApp"
        mock_result.timeout = 300
        mock_client.send_code_request = AsyncMock(return_value=mock_result)

        with patch("app.services.telegram_client.create_auth_client", new_callable=AsyncMock, return_value=mock_client):
            client, phone_hash, code_type = await request_code("+1234567890")
            assert phone_hash == "hash123"
            assert code_type == "app"

    async def test_flood_wait(self):
        from telethon.errors import FloodWaitError

        mock_client = AsyncMock()
        error = FloodWaitError(request=None, capture=0)
        error.seconds = 60
        mock_client.send_code_request = AsyncMock(side_effect=error)
        mock_client.disconnect = AsyncMock()

        with patch("app.services.telegram_client.create_auth_client", new_callable=AsyncMock, return_value=mock_client):
            with pytest.raises(ValueError, match="Too many attempts"):
                await request_code("+1234567890")


class TestVerifyCode:
    async def test_success(self):
        mock_client = AsyncMock()
        mock_me = MagicMock()
        mock_me.id = 12345
        mock_client.sign_in = AsyncMock(return_value=mock_me)
        mock_client.get_me = AsyncMock(return_value=mock_me)
        mock_client.session = MagicMock()
        mock_client.session.save = MagicMock(return_value="session_string")

        session_str, user_id = await verify_code(
            mock_client, "+1234567890", "hash123", "12345"
        )
        assert session_str == "session_string"
        assert user_id == 12345

    async def test_2fa_without_password(self):
        from telethon.errors import SessionPasswordNeededError

        mock_client = AsyncMock()
        mock_client.sign_in = AsyncMock(
            side_effect=SessionPasswordNeededError(request=None)
        )

        with pytest.raises(ValueError, match="Two-factor"):
            await verify_code(mock_client, "+1234567890", "hash123", "12345")

    async def test_2fa_with_password(self):
        from telethon.errors import SessionPasswordNeededError

        mock_client = AsyncMock()
        mock_me = MagicMock()
        mock_me.id = 12345
        # First call raises 2FA, second call succeeds
        mock_client.sign_in = AsyncMock(
            side_effect=[SessionPasswordNeededError(request=None), mock_me]
        )
        mock_client.get_me = AsyncMock(return_value=mock_me)
        mock_client.session = MagicMock()
        mock_client.session.save = MagicMock(return_value="session_string")

        session_str, user_id = await verify_code(
            mock_client, "+1234567890", "hash123", "12345", password="my2fa"
        )
        assert session_str == "session_string"
