from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_api_key,
    compute_api_key_prefix,
    get_key_hint,
)
from app.models.api_key import ApiKey
from app.models.user import User


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
