from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.models.session import TelegramSession
from app.models.settings import UserSettings
from app.services.telegram_client import (
    TelegramSessionUnauthorizedError,
    _get_code_type_name,
    get_client,
    invalidate_unauthorized_session,
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

        with patch(
            "app.services.telegram_client.create_auth_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            client, phone_hash, code_type = await request_code("+1234567890")
            assert client is mock_client
            assert phone_hash == "hash123"
            assert code_type == "app"

    async def test_flood_wait(self):
        from telethon.errors import FloodWaitError

        mock_client = AsyncMock()
        error = FloodWaitError(request=None, capture=0)
        error.seconds = 60
        mock_client.send_code_request = AsyncMock(side_effect=error)
        mock_client.disconnect = AsyncMock()

        with patch(
            "app.services.telegram_client.create_auth_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
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
        assert user_id == 12345


class TestGetClient:
    async def test_unauthorized_session_is_disabled(self, db_session, test_user):
        active_session = TelegramSession(
            user_id=test_user.id,
            phone_number="+1234567890",
            session_string="encrypted",
            telegram_user_id=12345,
            is_active=True,
        )
        user_settings = UserSettings(
            user_id=test_user.id,
            realtime_sync_enabled=True,
        )
        db_session.add_all([active_session, user_settings])
        await db_session.flush()

        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.get_me = AsyncMock(return_value=None)
        mock_client.disconnect = AsyncMock()

        mock_redis = AsyncMock()

        @asynccontextmanager
        async def fake_get_db_context():
            yield db_session
            await db_session.flush()

        with (
            patch(
                "app.services.telegram_client.TelegramClient",
                return_value=mock_client,
            ),
            patch(
                "app.services.telegram_client.StringSession",
                return_value=MagicMock(),
            ),
            patch(
                "app.services.telegram_client.decrypt_session",
                return_value="decrypted-session",
            ),
            patch(
                "app.services.telegram_client.get_db_context",
                fake_get_db_context,
            ),
            patch(
                "app.services.telegram_client.aioredis.from_url",
                return_value=mock_redis,
            ),
        ):
            with pytest.raises(TelegramSessionUnauthorizedError):
                await get_client(test_user.id, db_session)

        await db_session.refresh(active_session)
        await db_session.refresh(user_settings)

        assert active_session.is_active is False
        assert user_settings.realtime_sync_enabled is False
        mock_client.disconnect.assert_awaited_once()
        mock_redis.delete.assert_awaited_once()
        mock_redis.publish.assert_awaited_once()
        mock_redis.aclose.assert_awaited_once()

    async def test_transient_rpc_error_does_not_disable_session(
        self, db_session, test_user
    ):
        from telethon.errors import FloodWaitError

        active_session = TelegramSession(
            user_id=test_user.id,
            phone_number="+1234567890",
            session_string="encrypted",
            telegram_user_id=12345,
            is_active=True,
        )
        user_settings = UserSettings(
            user_id=test_user.id,
            realtime_sync_enabled=True,
        )
        db_session.add_all([active_session, user_settings])
        await db_session.flush()

        flood_wait = FloodWaitError(request=None, capture=30)
        flood_wait.seconds = 30

        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.get_me = AsyncMock(side_effect=flood_wait)
        mock_client.disconnect = AsyncMock()
        mock_redis = AsyncMock()

        @asynccontextmanager
        async def fake_get_db_context():
            yield db_session
            await db_session.flush()

        with (
            patch(
                "app.services.telegram_client.TelegramClient",
                return_value=mock_client,
            ),
            patch(
                "app.services.telegram_client.StringSession",
                return_value=MagicMock(),
            ),
            patch(
                "app.services.telegram_client.decrypt_session",
                return_value="decrypted-session",
            ),
            patch(
                "app.services.telegram_client.get_db_context",
                fake_get_db_context,
            ),
            patch(
                "app.services.telegram_client.aioredis.from_url",
                return_value=mock_redis,
            ),
        ):
            with pytest.raises(FloodWaitError):
                await get_client(test_user.id, db_session)

        await db_session.refresh(active_session)
        await db_session.refresh(user_settings)

        assert active_session.is_active is True
        assert user_settings.realtime_sync_enabled is True
        mock_redis.delete.assert_not_called()
        mock_redis.publish.assert_not_called()


class TestInvalidateUnauthorizedSession:
    async def test_only_matching_session_is_disabled(self, db_session, test_user):
        stale_session = TelegramSession(
            user_id=test_user.id,
            phone_number="+1111111111",
            session_string="stale",
            telegram_user_id=1,
            is_active=True,
        )
        fresh_session = TelegramSession(
            user_id=test_user.id,
            phone_number="+2222222222",
            session_string="fresh",
            telegram_user_id=2,
            is_active=True,
        )
        user_settings = UserSettings(
            user_id=test_user.id,
            realtime_sync_enabled=True,
        )
        db_session.add_all([stale_session, fresh_session, user_settings])
        await db_session.flush()

        mock_redis = AsyncMock()

        @asynccontextmanager
        async def fake_get_db_context():
            yield db_session
            await db_session.flush()

        with (
            patch(
                "app.services.telegram_client.get_db_context",
                fake_get_db_context,
            ),
            patch(
                "app.services.telegram_client.aioredis.from_url",
                return_value=mock_redis,
            ),
        ):
            changed = await invalidate_unauthorized_session(
                test_user.id,
                "session revoked",
                session_id=stale_session.id,
            )

        assert changed is True
        await db_session.refresh(stale_session)
        await db_session.refresh(fresh_session)
        await db_session.refresh(user_settings)

        assert stale_session.is_active is False
        assert fresh_session.is_active is True
        assert user_settings.realtime_sync_enabled is True
        assert mock_redis.publish.await_count == 2
        published_commands = [
            call.args[1]
            for call in mock_redis.publish.await_args_list
        ]
        assert '"command": "stop_user"' in published_commands[0]
        assert '"command": "start_user"' in published_commands[1]
