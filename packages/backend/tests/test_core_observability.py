import logging
from unittest.mock import MagicMock
from uuid import uuid4

from app.core.config import Settings
from app.core import observability


class FakeScope:
    def __init__(self):
        self.tags = {}
        self.contexts = {}
        self.user = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def set_tag(self, key, value):
        self.tags[key] = value

    def set_context(self, key, value):
        self.contexts[key] = value

    def set_user(self, value):
        self.user = value


class FakeSentrySDK:
    def __init__(self):
        self.init_calls = []
        self.global_user = None
        self.context_calls = []
        self.captured = []
        self.scope = FakeScope()
        self.push_scopes = []

    def init(self, **kwargs):
        self.init_calls.append(kwargs)

    def configure_scope(self):
        return self.scope

    def set_user(self, payload):
        self.global_user = payload

    def set_context(self, name, context):
        self.context_calls.append((name, context))

    def push_scope(self):
        scope = FakeScope()
        self.push_scopes.append(scope)
        return scope

    def capture_exception(self, exc):
        self.captured.append(exc)


class TestSanitizeData:
    def test_redacts_nested_sensitive_fields(self):
        payload = {
            "email": "user@example.com",
            "nested": {
                "session_string": "telegram-session",
                "safe_value": "ok",
            },
            "items": [{"phone_number": "+1000000"}],
        }

        sanitized = observability.sanitize_mapping(payload)

        assert sanitized["email"] == observability.REDACTED
        assert sanitized["nested"]["session_string"] == observability.REDACTED
        assert sanitized["nested"]["safe_value"] == "ok"
        assert sanitized["items"][0]["phone_number"] == observability.REDACTED

    def test_before_send_scrubs_request_user_and_breadcrumbs(self):
        event = {
            "request": {
                "headers": {
                    "Authorization": "Bearer secret",
                    "X-Request-ID": "req-1",
                },
                "data": {"password": "pw"},
                "cookies": {"sid": "cookie"},
            },
            "user": {"id": "user-1", "email": "user@example.com"},
            "extra": {"telegram_user_id": 12345, "status": "failed"},
            "breadcrumbs": {
                "values": [{"data": {"session_string": "secret", "phase": "startup"}}]
            },
        }

        sanitized = observability.before_send(event, {})

        assert (
            sanitized["request"]["headers"]["Authorization"] == observability.REDACTED
        )
        assert sanitized["request"]["headers"]["X-Request-ID"] == "req-1"
        assert sanitized["request"]["data"] == observability.REDACTED
        assert sanitized["request"]["cookies"] == observability.REDACTED
        assert sanitized["user"]["id"] == "user-1"
        assert sanitized["user"]["email"] == observability.REDACTED
        assert sanitized["extra"]["telegram_user_id"] == observability.REDACTED
        assert sanitized["extra"]["status"] == "failed"
        assert (
            sanitized["breadcrumbs"]["values"][0]["data"]["session_string"]
            == observability.REDACTED
        )

    def test_before_send_log_scrubs_attributes(self):
        log = {
            "body": "Login failed",
            "attributes": {"email": "user@example.com", "attempt": 2},
        }

        sanitized = observability.before_send_log(log, {})

        assert sanitized["attributes"]["email"] == observability.REDACTED
        assert sanitized["attributes"]["attempt"] == 2


class TestInitObservability:
    def test_returns_false_without_dsn(self, monkeypatch):
        fake_sdk = FakeSentrySDK()
        monkeypatch.setattr(observability, "sentry_sdk", fake_sdk)

        settings = Settings(sentry_dsn="")

        assert observability.init_observability(settings, "svc") is False
        assert fake_sdk.init_calls == []

    def test_initializes_sentry_with_safe_defaults(self, monkeypatch):
        fake_sdk = FakeSentrySDK()

        class FakeCeleryIntegration:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class FakeScrubber:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        monkeypatch.setattr(observability, "sentry_sdk", fake_sdk)
        monkeypatch.setattr(observability, "CeleryIntegration", FakeCeleryIntegration)
        monkeypatch.setattr(observability, "EventScrubber", FakeScrubber)

        settings = Settings(
            sentry_dsn="https://public@example.ingest.sentry.io/1",
            sentry_release="release-123",
            sentry_traces_sample_rate=0.25,
            sentry_profiles_sample_rate=0.0,
            sentry_enable_logs=True,
        )

        result = observability.init_observability(
            settings,
            "wai-telegram-backend",
            enable_celery_monitoring=True,
        )

        assert result is True
        kwargs = fake_sdk.init_calls[0]
        assert kwargs["dsn"] == settings.sentry_dsn
        assert kwargs["release"] == "release-123"
        assert kwargs["send_default_pii"] is False
        assert kwargs["enable_logs"] is True
        assert kwargs["max_request_body_size"] == "never"
        assert kwargs["include_local_variables"] is False
        assert kwargs["integrations"][0].kwargs == {"monitor_beat_tasks": True}
        assert "email" in kwargs["event_scrubber"].kwargs["pii_denylist"]
        assert fake_sdk.scope.tags["service"] == "wai-telegram-backend"
        assert fake_sdk.scope.tags["environment"] == settings.environment


class TestSentryHelpers:
    def test_set_user_context_only_sets_safe_fields(self, monkeypatch):
        fake_sdk = FakeSentrySDK()
        monkeypatch.setattr(observability, "sentry_sdk", fake_sdk)

        observability.set_user_context(user_id=uuid4(), auth_type="jwt")

        assert set(fake_sdk.global_user.keys()) == {"id", "auth_type"}

    def test_capture_exception_sanitizes_contexts_and_tags(self, monkeypatch):
        fake_sdk = FakeSentrySDK()
        monkeypatch.setattr(observability, "sentry_sdk", fake_sdk)

        error = RuntimeError("boom")
        observability.capture_exception(
            error,
            user_id="user-1",
            contexts={"auth": {"email": "user@example.com", "attempt": 3}},
            tags={"token": "secret-token", "surface": "api"},
        )

        scope = fake_sdk.push_scopes[0]
        assert scope.user == {"id": "user-1"}
        assert scope.contexts["auth"]["email"] == observability.REDACTED
        assert scope.contexts["auth"]["attempt"] == 3
        assert scope.tags["token"] == observability.REDACTED
        assert scope.tags["surface"] == "api"
        assert fake_sdk.captured == [error]

    def test_log_event_adds_sanitized_extra(self):
        fake_logger = MagicMock(spec=logging.Logger)

        observability.log_event(
            fake_logger,
            logging.INFO,
            "Login succeeded",
            event_name="auth.login.success",
            user_id=uuid4(),
            email="user@example.com",
        )

        fake_logger.log.assert_called_once()
        kwargs = fake_logger.log.call_args.kwargs
        assert kwargs["extra"]["event_name"] == "auth.login.success"
        assert kwargs["extra"]["safe_context"]["email"] == observability.REDACTED
        assert "user_id" in kwargs["extra"]["safe_context"]
