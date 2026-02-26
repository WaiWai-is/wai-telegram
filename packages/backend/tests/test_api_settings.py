from unittest.mock import AsyncMock, MagicMock, patch

from app.models.session import TelegramSession
from app.models.settings import UserSettings


class TestGetSettings:
    async def test_get_creates_defaults(self, auth_client):
        mock_redis = MagicMock()
        mock_redis.get = MagicMock(return_value=None)

        with patch("app.api.v1.settings._redis", mock_redis):
            response = await auth_client.get("/api/v1/settings")
            assert response.status_code == 200
            data = response.json()
            assert data["digest_enabled"] is True
            assert data["digest_hour_utc"] == 9
            assert data["digest_timezone"] == "UTC"
            assert data["listener_active"] is False


class TestUpdateSettings:
    async def test_partial_update(self, auth_client):
        mock_redis = MagicMock()
        mock_redis.get = MagicMock(return_value=None)

        with patch("app.api.v1.settings._redis", mock_redis):
            response = await auth_client.put(
                "/api/v1/settings",
                json={"digest_hour_utc": 14},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["digest_hour_utc"] == 14
            assert data["digest_enabled"] is True  # unchanged default

    async def test_realtime_toggle_publishes_redis(
        self, auth_client, db_session, test_user
    ):
        # Create settings first
        settings = UserSettings(
            user_id=test_user.id,
            realtime_sync_enabled=False,
        )
        db_session.add(settings)
        await db_session.flush()

        mock_redis = MagicMock()
        mock_redis.get = MagicMock(return_value=None)
        mock_redis.publish = MagicMock()

        with patch("app.api.v1.settings._redis", mock_redis):
            response = await auth_client.put(
                "/api/v1/settings",
                json={"realtime_sync_enabled": True},
            )
            assert response.status_code == 200
            mock_redis.publish.assert_called_once()

    async def test_unauthenticated(self, client):
        response = await client.get("/api/v1/settings")
        assert response.status_code == 401


class TestTestBot:
    async def test_no_bot_token(self, auth_client):
        with patch("app.api.v1.settings.config") as mock_config:
            mock_config.telegram_bot_token = ""
            response = await auth_client.post("/api/v1/settings/test-bot")
            assert response.status_code == 503

    async def test_no_session(self, auth_client):
        with patch("app.api.v1.settings.config") as mock_config:
            mock_config.telegram_bot_token = "bot-token-123"
            response = await auth_client.post("/api/v1/settings/test-bot")
            assert response.status_code == 400

    async def test_success(self, auth_client, db_session, test_user):
        session = TelegramSession(
            user_id=test_user.id,
            phone_number="+1234567890",
            session_string="encrypted",
            telegram_user_id=12345,
            is_active=True,
        )
        db_session.add(session)
        await db_session.flush()

        with (
            patch("app.api.v1.settings.config") as mock_config,
            patch("app.api.v1.settings.send_telegram_message", new_callable=AsyncMock),
        ):
            mock_config.telegram_bot_token = "bot-token-123"
            response = await auth_client.post("/api/v1/settings/test-bot")
            assert response.status_code == 200
            assert response.json()["success"] is True
