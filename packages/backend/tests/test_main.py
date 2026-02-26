from unittest.mock import AsyncMock, patch


class TestLivenessCheck:
    async def test_returns_alive(self, client):
        response = await client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "alive"}

    async def test_head_method(self, client):
        response = await client.head("/health/live")
        assert response.status_code == 200


class TestReadinessCheck:
    async def test_returns_ready(self, client):
        with patch("app.main._check_dependencies", new_callable=AsyncMock):
            response = await client.get("/health/ready")
            assert response.status_code == 200
            assert response.json() == {"status": "ready"}

    async def test_fails_when_deps_down(self, client):
        import pytest

        with patch(
            "app.main._check_dependencies",
            new_callable=AsyncMock,
            side_effect=Exception("DB down"),
        ):
            with pytest.raises(Exception, match="DB down"):
                await client.get("/health/ready")


class TestHealthCheck:
    async def test_returns_healthy(self, client):
        with patch("app.main._check_dependencies", new_callable=AsyncMock):
            response = await client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "healthy"}


class TestCORSDevOrigins:
    async def test_localhost_3000_allowed(self, client):
        response = await client.options(
            "/health/live",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert (
            response.headers.get("access-control-allow-origin")
            == "http://localhost:3000"
        )

    async def test_unknown_origin_rejected(self, client):
        response = await client.options(
            "/health/live",
            headers={
                "Origin": "https://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.headers.get("access-control-allow-origin") is None


class TestAPIRouterMounted:
    async def test_api_v1_prefix(self, client):
        response = await client.get("/api/v1/auth/me")
        # Should get 401 (not 404), proving the router is mounted
        assert response.status_code == 401
