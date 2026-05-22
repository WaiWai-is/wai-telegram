from __future__ import annotations

import logging
import os
import re
from importlib.metadata import PackageNotFoundError, version
from collections.abc import Iterable
from typing import Any, Mapping
from uuid import UUID

try:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.scrubber import EventScrubber
except ImportError:  # pragma: no cover - handled in tests via monkeypatching
    CeleryIntegration = None  # type: ignore[assignment]
    EventScrubber = None  # type: ignore[assignment]
    sentry_sdk = None  # type: ignore[assignment]

from app.core.config import Settings

logger = logging.getLogger(__name__)

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
REDACTED = "[redacted]"
SAFE_USER_FIELDS = {"id"}
SENSITIVE_KEYS = frozenset(
    {
        "access_hash",
        "api_hash",
        "api_key",
        "api_token",
        "authorization",
        "cookie",
        "cookies",
        "email",
        "encryption_key",
        "message_text",
        "password",
        "phone",
        "phone_number",
        "prompt",
        "query",
        "response",
        "secret",
        "session",
        "session_string",
        "telegram_api_hash",
        "telegram_bot_token",
        "telegram_user_id",
        "text",
        "token",
        "transcript",
    }
)
SENSITIVE_SUBSTRINGS = (
    "authorization",
    "cookie",
    "email",
    "password",
    "phone",
    "prompt",
    "secret",
    "session",
    "telegram_user",
    "text",
    "token",
    "transcript",
)

# Patterns for secrets that can appear inside free-text messages/exceptions
# (where key-based scrubbing does not reach). Telegram bot tokens look like
# "<bot_id>:<35-char base64url secret>" and leak via API URLs in httpx errors.
_SECRET_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}"),
)


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format=DEFAULT_LOG_FORMAT)


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(".", "_")


def _is_sensitive_key(key: str | None) -> bool:
    if not key:
        return False
    normalized = _normalize_key(key)
    return normalized in SENSITIVE_KEYS or any(
        fragment in normalized for fragment in SENSITIVE_SUBSTRINGS
    )


def sanitize_data(value: Any, key: str | None = None) -> Any:
    if _is_sensitive_key(key):
        return REDACTED

    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_data(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [sanitize_data(item, key) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_data(item, key) for item in value)
    if isinstance(value, set):
        return sorted(sanitize_data(item, key) for item in value)
    if isinstance(value, UUID):
        return str(value)
    return value


def sanitize_mapping(mapping: Mapping[str, Any] | None) -> dict[str, Any]:
    if not mapping:
        return {}
    return {str(key): sanitize_data(value, str(key)) for key, value in mapping.items()}


def _sanitize_request_payload(event: dict[str, Any]) -> None:
    request = event.get("request")
    if not isinstance(request, dict):
        return

    headers = request.get("headers")
    if isinstance(headers, Mapping):
        request["headers"] = {
            str(key): REDACTED if _is_sensitive_key(str(key)) else value
            for key, value in headers.items()
        }

    for request_key in ("data", "cookies", "env"):
        if request_key in request:
            request[request_key] = REDACTED


def _sanitize_user_payload(event: dict[str, Any]) -> None:
    user = event.get("user")
    if not isinstance(user, dict):
        return

    sanitized_user = {}
    for key, value in user.items():
        normalized = _normalize_key(str(key))
        if normalized in SAFE_USER_FIELDS:
            sanitized_user[str(key)] = value
        else:
            sanitized_user[str(key)] = REDACTED
    event["user"] = sanitized_user


def _sanitize_breadcrumbs(event: dict[str, Any]) -> None:
    breadcrumbs = event.get("breadcrumbs")
    if not isinstance(breadcrumbs, dict):
        return
    values = breadcrumbs.get("values")
    if not isinstance(values, list):
        return
    for breadcrumb in values:
        if not isinstance(breadcrumb, dict):
            continue
        data = breadcrumb.get("data")
        if isinstance(data, Mapping):
            breadcrumb["data"] = sanitize_mapping(data)


def _scrub_secret_text(text: str) -> str:
    for pattern in _SECRET_TEXT_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def _sanitize_event_text(event: dict[str, Any]) -> None:
    """Redact secrets embedded in free-text exception/log/message fields."""
    exception = event.get("exception")
    if isinstance(exception, Mapping):
        for value in exception.get("values") or ():
            if isinstance(value, dict) and isinstance(value.get("value"), str):
                value["value"] = _scrub_secret_text(value["value"])
    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        for key in ("formatted", "message"):
            if isinstance(logentry.get(key), str):
                logentry[key] = _scrub_secret_text(logentry[key])
    if isinstance(event.get("message"), str):
        event["message"] = _scrub_secret_text(event["message"])


def _sanitize_event(event: dict[str, Any]) -> dict[str, Any]:
    for top_level_key in ("contexts", "extra", "tags"):
        value = event.get(top_level_key)
        if isinstance(value, Mapping):
            event[top_level_key] = sanitize_mapping(value)

    _sanitize_request_payload(event)
    _sanitize_user_payload(event)
    _sanitize_breadcrumbs(event)
    _sanitize_event_text(event)
    return event


NOISY_EVENT_PATTERNS: tuple[str, ...] = (
    "Event loop is closed",
    "Telethon session not authorized",
    "No active Telegram session found",
)


def _event_text_fragments(event: Mapping[str, Any]) -> Iterable[str]:
    exception = event.get("exception")
    if isinstance(exception, Mapping):
        for value in exception.get("values") or ():
            if isinstance(value, Mapping):
                msg = value.get("value")
                if isinstance(msg, str):
                    yield msg
    logentry = event.get("logentry")
    if isinstance(logentry, Mapping):
        for key in ("formatted", "message"):
            msg = logentry.get(key)
            if isinstance(msg, str):
                yield msg
    top_message = event.get("message")
    if isinstance(top_message, str):
        yield top_message


def _is_known_noise(event: Mapping[str, Any]) -> bool:
    return any(
        pattern in fragment
        for fragment in _event_text_fragments(event)
        for pattern in NOISY_EVENT_PATTERNS
    )


def before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    if _is_known_noise(event):
        return None
    return _sanitize_event(event)


def before_send_transaction(
    event: dict[str, Any], _hint: dict[str, Any]
) -> dict[str, Any]:
    return _sanitize_event(event)


def before_breadcrumb(
    crumb: dict[str, Any], _hint: dict[str, Any]
) -> dict[str, Any] | None:
    data = crumb.get("data")
    if isinstance(data, Mapping):
        crumb["data"] = sanitize_mapping(data)
    return crumb


def before_send_log(
    log: dict[str, Any], _hint: dict[str, Any]
) -> dict[str, Any] | None:
    attributes = log.get("attributes")
    if isinstance(attributes, Mapping):
        log["attributes"] = sanitize_mapping(attributes)
    return log


def _build_release_name(settings: Settings, service_name: str) -> str:
    if settings.sentry_release:
        return settings.sentry_release
    try:
        package_version = version("wai-telegram-backend")
    except (
        PackageNotFoundError
    ):  # pragma: no cover - only during unusual packaging failures
        package_version = "0.0.0"
    return f"{service_name}@{package_version}"


def init_observability(
    settings: Settings,
    service_name: str,
    *,
    enable_celery_monitoring: bool = False,
) -> bool:
    if not settings.sentry_dsn:
        logger.info("Sentry is disabled for service %s", service_name)
        return False

    if sentry_sdk is None:
        logger.warning("Sentry SDK is unavailable for service %s", service_name)
        return False

    integrations: list[Any] = []
    if enable_celery_monitoring and CeleryIntegration is not None:
        integrations.append(CeleryIntegration(monitor_beat_tasks=True))

    scrubber = None
    if EventScrubber is not None:
        scrubber = EventScrubber(
            pii_denylist=list(SENSITIVE_KEYS),
        )

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=_build_release_name(settings, service_name),
        send_default_pii=False,
        event_scrubber=scrubber,
        before_send=before_send,
        before_send_transaction=before_send_transaction,
        before_breadcrumb=before_breadcrumb,
        before_send_log=before_send_log,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        enable_logs=settings.sentry_enable_logs,
        debug=settings.sentry_debug,
        max_request_body_size="never",
        include_local_variables=False,
        attach_stacktrace=True,
        max_breadcrumbs=100,
        integrations=integrations,
    )

    with sentry_sdk.configure_scope() as scope:
        scope.set_tag("service", service_name)
        scope.set_tag("environment", settings.environment)

    logger.info("Sentry initialized for service %s", service_name)
    return True


def set_user_context(
    *,
    user_id: UUID | str | None = None,
    auth_type: str | None = None,
) -> None:
    if sentry_sdk is None:
        return

    if user_id is None:
        sentry_sdk.set_user(None)
        return

    user_payload: dict[str, Any] = {"id": str(user_id)}
    if auth_type:
        user_payload["auth_type"] = auth_type
    sentry_sdk.set_user(user_payload)


def set_safe_context(name: str, context: Mapping[str, Any]) -> None:
    if sentry_sdk is None:
        return
    sentry_sdk.set_context(name, sanitize_mapping(context))


def capture_exception(
    exc: BaseException,
    *,
    user_id: UUID | str | None = None,
    contexts: Mapping[str, Mapping[str, Any]] | None = None,
    tags: Mapping[str, Any] | None = None,
) -> None:
    if sentry_sdk is None:
        return

    with sentry_sdk.push_scope() as scope:
        if user_id is not None:
            scope.set_user({"id": str(user_id)})
        for name, context in (contexts or {}).items():
            scope.set_context(name, sanitize_mapping(context))
        for key, value in (tags or {}).items():
            scope.set_tag(str(key), sanitize_data(value, str(key)))
        sentry_sdk.capture_exception(exc)


def log_event(
    logger_instance: logging.Logger,
    level: int,
    message: str,
    *,
    event_name: str,
    **context: Any,
) -> None:
    safe_context = sanitize_mapping(context)
    extra = {"event_name": event_name}
    if safe_context:
        extra["safe_context"] = safe_context
    logger_instance.log(level, message, extra=extra)


def build_runtime_summary(*, service_name: str, settings: Settings) -> dict[str, Any]:
    return {
        "service": service_name,
        "environment": settings.environment,
        "release": _build_release_name(settings, service_name),
        "logs_enabled": settings.sentry_enable_logs,
        "dsn_configured": bool(settings.sentry_dsn),
        "host": os.environ.get("HOSTNAME"),
    }
