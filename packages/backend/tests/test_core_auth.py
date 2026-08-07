from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.core.security import (
    compute_api_key_prefix,
    create_access_token,
    create_refresh_token,
    get_key_hint,
    hash_api_key,
)
from app.models.api_key import ApiKey


class TestGetCurrentUserJWT:
    async def test_valid_access_token(self, client, auth_client, test_user):
        response = await auth_client.get("/api/v1/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user.email

    async def test_no_credentials_returns_401(self, client):
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401

    async def test_invalid_token_returns_401(self, client):
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert response.status_code == 401

    async def test_expired_token_returns_401(self, client, test_user):
        token = create_access_token(
            {"sub": str(test_user.id)},
            expires_delta=timedelta(seconds=-1),
        )
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer " + token},
        )
        assert response.status_code == 401

    async def test_refresh_token_rejected_for_access(self, client, test_user):
        token = create_refresh_token({"sub": str(test_user.id)})
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer " + token},
        )
        assert response.status_code == 401

    async def test_nonexistent_user_returns_401(self, client):
        token = create_access_token({"sub": str(uuid4())})
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer " + token},
        )
        assert response.status_code == 401

    async def test_inactive_user_existing_jwt_returns_401(
        self, client, db_session, test_user
    ):
        token = create_access_token({"sub": str(test_user.id)})
        test_user.is_active = False
        await db_session.flush()

        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer " + token},
        )

        assert response.status_code == 401


class TestGetCurrentUserApiKey:
    async def test_valid_api_key(self, client, db_session, test_user):
        raw_key = "wai_testapikey1234567890abcdefghij"
        api_key = ApiKey(
            user_id=test_user.id,
            name="Test Key",
            key_hash=hash_api_key(raw_key),
            key_prefix=compute_api_key_prefix(raw_key),
            key_hint=get_key_hint(raw_key),
            is_active=True,
        )
        db_session.add(api_key)
        await db_session.flush()

        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert response.status_code == 200
        assert response.json()["email"] == test_user.email

    async def test_inactive_api_key_returns_401(self, client, db_session, test_user):
        raw_key = "wai_inactivekey1234567890abcdefgh"
        api_key = ApiKey(
            user_id=test_user.id,
            name="Inactive Key",
            key_hash=hash_api_key(raw_key),
            key_prefix=compute_api_key_prefix(raw_key),
            key_hint=get_key_hint(raw_key),
            is_active=False,
        )
        db_session.add(api_key)
        await db_session.flush()

        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert response.status_code == 401

    async def test_active_key_for_inactive_user_returns_401(
        self, client, db_session, test_user
    ):
        raw_key = "wai_inactiveuser1234567890abcdefgh"
        api_key = ApiKey(
            user_id=test_user.id,
            name="Inactive User Key",
            key_hash=hash_api_key(raw_key),
            key_prefix=compute_api_key_prefix(raw_key),
            key_hint=get_key_hint(raw_key),
            is_active=True,
        )
        db_session.add(api_key)
        test_user.is_active = False
        await db_session.flush()

        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {raw_key}"},
        )

        assert response.status_code == 401
        assert api_key.last_used_at is None

    async def test_expired_api_key_returns_401(self, client, db_session, test_user):
        raw_key = "wai_expiredkey1234567890abcdefghij"
        api_key = ApiKey(
            user_id=test_user.id,
            name="Expired Key",
            key_hash=hash_api_key(raw_key),
            key_prefix=compute_api_key_prefix(raw_key),
            key_hint=get_key_hint(raw_key),
            is_active=True,
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        db_session.add(api_key)
        await db_session.flush()

        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert response.status_code == 401

    async def test_read_only_api_key_cannot_access_write_routes(
        self, client, db_session, test_user
    ):
        raw_key = "wai_readonlykey1234567890abcdefgh"
        api_key = ApiKey(
            user_id=test_user.id,
            name="Read Only Key",
            key_hash=hash_api_key(raw_key),
            key_prefix=compute_api_key_prefix(raw_key),
            key_hint=get_key_hint(raw_key),
            is_active=True,
            scopes="read",
        )
        db_session.add(api_key)
        await db_session.flush()

        # Outbound-effect endpoint (sends a message to Telegram) must stay gated.
        response = await client.post(
            f"/api/v1/messages/{uuid4()}/send",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={"text": "hello"},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "API key lacks 'write' permission"

    async def test_read_only_api_key_can_trigger_sync(
        self, client, db_session, test_user
    ):
        """Local-cache data pulls (sync) are read-level — no write scope needed."""
        raw_key = "wai_readonlysync1234567890abcdef"
        api_key = ApiKey(
            user_id=test_user.id,
            name="Read Only Sync Key",
            key_hash=hash_api_key(raw_key),
            key_prefix=compute_api_key_prefix(raw_key),
            key_hint=get_key_hint(raw_key),
            is_active=True,
            scopes="read",
        )
        db_session.add(api_key)
        await db_session.flush()

        mock_task = MagicMock()
        mock_task.delay = MagicMock()
        with (
            patch("app.api.v1.sync.sync_all_chats_task", mock_task),
            patch("app.api.v1.sync.redis_client", MagicMock()),
        ):
            response = await client.post(
                "/api/v1/sync/all",
                headers={"Authorization": f"Bearer {raw_key}"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "pending"
        mock_task.delay.assert_called_once()
