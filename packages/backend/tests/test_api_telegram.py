from unittest.mock import AsyncMock, MagicMock, patch

from app.models.session import TelegramSession


class TestRequestCode:
    async def test_request_code_success(self, auth_client):
        mock_client = MagicMock()

        with patch(
            "app.services.telegram_client.request_code",
            new_callable=AsyncMock,
            return_value=(mock_client, "hash123", "app"),
        ):
            response = await auth_client.post(
                "/api/v1/telegram/request-code",
                json={"phone_number": "+1234567890"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["phone_code_hash"] == "hash123"
            assert data["code_type"] == "app"

    async def test_request_code_flood(self, auth_client):
        with patch(
            "app.services.telegram_client.request_code",
            new_callable=AsyncMock,
            side_effect=ValueError("Too many attempts. Please wait 120 seconds."),
        ):
            response = await auth_client.post(
                "/api/v1/telegram/request-code",
                json={"phone_number": "+1234567890"},
            )
            assert response.status_code == 429


class TestVerifyCode:
    async def test_verify_no_pending(self, auth_client):
        response = await auth_client.post(
            "/api/v1/telegram/verify-code",
            json={
                "phone_number": "+1234567890",
                "phone_code_hash": "hash123",
                "code": "12345",
            },
        )
        assert response.status_code == 400
        assert "No pending" in response.json()["detail"]


class TestGetSession:
    async def test_get_session_exists(self, auth_client, db_session, test_user):
        session = TelegramSession(
            user_id=test_user.id,
            phone_number="+1234567890",
            session_string="encrypted_session",
            telegram_user_id=12345,
            is_active=True,
        )
        db_session.add(session)
        await db_session.flush()

        response = await auth_client.get("/api/v1/telegram/session")
        assert response.status_code == 200
        data = response.json()
        assert data["phone_number"] == "+1234567890"

    async def test_get_session_none(self, auth_client):
        response = await auth_client.get("/api/v1/telegram/session")
        assert response.status_code == 200
        assert response.json() is None


class TestDeleteSession:
    async def test_delete_session(self, auth_client, db_session, test_user):
        session = TelegramSession(
            user_id=test_user.id,
            phone_number="+1234567890",
            session_string="encrypted_session",
            telegram_user_id=12345,
            is_active=True,
        )
        db_session.add(session)
        await db_session.flush()

        with patch(
            "app.services.telegram_client.disconnect_client",
            new_callable=AsyncMock,
        ):
            response = await auth_client.delete("/api/v1/telegram/session")
            assert response.status_code == 200
