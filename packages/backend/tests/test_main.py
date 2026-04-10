from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models.sync_job import SyncStatus


class _FakeScalarResult:
    def __init__(self, jobs):
        self._jobs = jobs

    def scalars(self):
        return self

    def all(self):
        return self._jobs


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


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


class TestLifespan:
    async def test_marks_orphaned_jobs_without_heartbeat(self):
        from app.main import lifespan

        job = SimpleNamespace(
            id="job-1",
            chat_id=None,
            status=SyncStatus.IN_PROGRESS,
            error_message=None,
        )
        fake_db = AsyncMock()
        fake_db.execute.return_value = _FakeScalarResult([job])
        fake_redis = SimpleNamespace(get=lambda _key: None, close=lambda: None)

        with (
            patch(
                "app.main.async_session_factory",
                return_value=_FakeSessionContext(fake_db),
            ),
            patch("redis.from_url", return_value=fake_redis),
        ):
            async with lifespan(None):
                pass

        assert job.status == SyncStatus.FAILED
        assert "orphaned" in job.error_message
        fake_db.commit.assert_awaited_once()

    async def test_startup_exception_is_captured(self):
        from app.main import lifespan

        with (
            patch("redis.from_url", side_effect=RuntimeError("redis unavailable")),
            patch("app.main.capture_exception") as mock_capture_exception,
        ):
            async with lifespan(None):
                pass

        mock_capture_exception.assert_called_once()
        assert isinstance(mock_capture_exception.call_args.args[0], RuntimeError)

    async def test_shutdown_disconnects_temporary_auth_clients(self):
        from app.api.v1 import telegram as telegram_api
        from app.main import lifespan

        fake_db = AsyncMock()
        fake_db.execute.return_value = _FakeScalarResult([])
        fake_redis = SimpleNamespace(get=lambda _key: None, close=lambda: None)
        fake_client = AsyncMock()

        with (
            patch(
                "app.main.async_session_factory",
                return_value=_FakeSessionContext(fake_db),
            ),
            patch("redis.from_url", return_value=fake_redis),
            patch.dict(
                telegram_api._auth_clients,
                {"client-1": (fake_client, None)},
                clear=True,
            ),
        ):
            async with lifespan(None):
                pass

        fake_client.disconnect.assert_awaited_once()
        assert telegram_api._auth_clients == {}
