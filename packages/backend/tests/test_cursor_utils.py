from datetime import UTC, datetime

import pytest

from app.core.cursor import CursorError, decode_cursor, encode_cursor, parse_cursor_datetime


def test_cursor_roundtrip() -> None:
    payload = {
        "id": "00000000-0000-0000-0000-000000000001",
        "sent_at": "2026-02-25T10:00:00+00:00",
        "telegram_message_id": 123,
    }
    encoded = encode_cursor(payload)
    decoded = decode_cursor(encoded)
    assert decoded == payload


def test_decode_cursor_rejects_invalid_payload() -> None:
    with pytest.raises(CursorError):
        decode_cursor("not-a-valid-cursor")


def test_parse_cursor_datetime_normalizes_utc() -> None:
    parsed = parse_cursor_datetime("2026-02-25T10:00:00+03:00")
    assert parsed == datetime(2026, 2, 25, 7, 0, tzinfo=UTC)
