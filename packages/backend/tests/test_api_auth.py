from uuid import uuid4

from app.core.security import (
    compute_api_key_prefix,
    create_access_token,
    create_refresh_token,
    get_key_hint,
    hash_api_key,
)
from app.models.api_key import ApiKey


class TestRegister:
    async def test_register_success(self, client):
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": "new@example.com", "password": "StrongPass1"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_register_duplicate_email(self, client, test_user):
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": test_user.email, "password": "StrongPass1"},
        )
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"]

    async def test_register_weak_password(self, client):
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": "weak@example.com", "password": "short"},
        )
        assert response.status_code == 422


class TestLogin:
    async def test_login_success(self, client, test_user):
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": test_user.email, "password": "TestPassword1"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_login_wrong_password(self, client, test_user):
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": test_user.email, "password": "WrongPassword1"},
        )
        assert response.status_code == 401
        assert "Invalid email or password" in response.json()["detail"]

    async def test_login_nonexistent_user(self, client):
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": "noone@example.com", "password": "AnyPass1"},
        )
        assert response.status_code == 401


class TestRefresh:
    async def test_refresh_valid(self, client, test_user):
        refresh = create_refresh_token({"sub": str(test_user.id)})
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_refresh_with_access_token_rejected(self, client, test_user):
        access = create_access_token({"sub": str(test_user.id)})
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": access},
        )
        assert response.status_code == 401

    async def test_refresh_invalid_token(self, client):
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "not.a.valid.token"},
        )
        assert response.status_code == 401

    async def test_refresh_nonexistent_user(self, client):
        refresh = create_refresh_token({"sub": str(uuid4())})
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh},
        )
        assert response.status_code == 401


class TestMe:
    async def test_me_authenticated(self, auth_client, test_user):
        response = await auth_client.get("/api/v1/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user.email
        assert data["id"] == str(test_user.id)

    async def test_me_unauthenticated(self, client):
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401


class TestApiKeys:
    async def test_create_api_key(self, auth_client):
        response = await auth_client.post(
            "/api/v1/auth/api-keys",
            json={"name": "Test Key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Key"
        assert data["api_key"].startswith("wai_")
        assert "key_hint" in data

    async def test_list_api_keys(self, auth_client, db_session, test_user):
        raw_key = "wai_listtest123456789012345678901"
        api_key = ApiKey(
            user_id=test_user.id,
            name="Listed Key",
            key_hash=hash_api_key(raw_key),
            key_prefix=compute_api_key_prefix(raw_key),
            key_hint=get_key_hint(raw_key),
        )
        db_session.add(api_key)
        await db_session.flush()

        response = await auth_client.get("/api/v1/auth/api-keys")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert any(k["name"] == "Listed Key" for k in data)

    async def test_delete_api_key(self, auth_client, db_session, test_user):
        raw_key = "wai_deletetest12345678901234567890"
        api_key = ApiKey(
            user_id=test_user.id,
            name="To Delete",
            key_hash=hash_api_key(raw_key),
            key_prefix=compute_api_key_prefix(raw_key),
            key_hint=get_key_hint(raw_key),
        )
        db_session.add(api_key)
        await db_session.flush()

        response = await auth_client.delete(f"/api/v1/auth/api-keys/{api_key.id}")
        assert response.status_code == 204

    async def test_delete_nonexistent_api_key(self, auth_client):
        response = await auth_client.delete(f"/api/v1/auth/api-keys/{uuid4()}")
        assert response.status_code == 404

    async def test_toggle_api_key(self, auth_client, db_session, test_user):
        raw_key = "wai_toggletest1234567890123456789"
        api_key = ApiKey(
            user_id=test_user.id,
            name="To Toggle",
            key_hash=hash_api_key(raw_key),
            key_prefix=compute_api_key_prefix(raw_key),
            key_hint=get_key_hint(raw_key),
            is_active=True,
        )
        db_session.add(api_key)
        await db_session.flush()

        response = await auth_client.patch(
            f"/api/v1/auth/api-keys/{api_key.id}",
            json={"is_active": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is False

    async def test_api_keys_unauthenticated(self, client):
        response = await client.get("/api/v1/auth/api-keys")
        assert response.status_code == 401
