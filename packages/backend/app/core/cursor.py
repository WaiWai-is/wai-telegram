import base64
import json
from datetime import UTC, datetime
from typing import Any


class CursorError(ValueError):
    """Raised when a pagination cursor is malformed."""


def encode_cursor(payload: dict[str, Any]) -> str:
    """Encode a cursor payload into a URL-safe token."""
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str, *, max_length: int = 2048) -> dict[str, Any]:
    """Decode a URL-safe cursor token."""
    if not cursor or len(cursor) > max_length:
        raise CursorError("Invalid cursor")

    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive guard
        raise CursorError("Invalid cursor") from exc

    if not isinstance(data, dict):
        raise CursorError("Invalid cursor")
    return data


def parse_cursor_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime stored in cursors, normalizing to UTC."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CursorError("Invalid cursor datetime") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
