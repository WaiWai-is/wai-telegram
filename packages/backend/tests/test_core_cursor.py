from datetime import UTC, datetime

import pytest
from app.core.cursor import (
    CursorError,
    decode_cursor,
    encode_cursor,
    parse_cursor_datetime,
)


class TestCursorRoundtrip:
    def test_encode_decode_roundtrip(self):
        payload = {
            "id": "00000000-0000-0000-0000-000000000001",
            "sent_at": "2026-02-25T10:00:00+00:00",
            "telegram_message_id": 123,
        }
        encoded = encode_cursor(payload)
        decoded = decode_cursor(encoded)
        assert decoded == payload

    def test_encode_produces_url_safe_string(self):
        payload = {"key": "value"}
        encoded = encode_cursor(payload)
        assert "=" not in encoded  # padding stripped
        assert " " not in encoded

    def test_decode_empty_cursor_raises(self):
        with pytest.raises(CursorError):
            decode_cursor("")

    def test_decode_invalid_base64_raises(self):
        with pytest.raises(CursorError):
            decode_cursor("not-a-valid-cursor")

    def test_decode_too_long_cursor_raises(self):
        with pytest.raises(CursorError):
            decode_cursor("a" * 2049)

    def test_decode_non_dict_payload_raises(self):
        import base64
        import json

        data = (
            base64.urlsafe_b64encode(json.dumps([1, 2, 3]).encode())
            .decode()
            .rstrip("=")
        )
        with pytest.raises(CursorError):
            decode_cursor(data)


class TestParseCursorDatetime:
    def test_none_returns_none(self):
        assert parse_cursor_datetime(None) is None

    def test_utc_datetime(self):
        parsed = parse_cursor_datetime("2026-02-25T10:00:00+00:00")
        assert parsed == datetime(2026, 2, 25, 10, 0, tzinfo=UTC)

    def test_normalizes_timezone_to_utc(self):
        parsed = parse_cursor_datetime("2026-02-25T10:00:00+03:00")
        assert parsed == datetime(2026, 2, 25, 7, 0, tzinfo=UTC)

    def test_naive_datetime_gets_utc(self):
        parsed = parse_cursor_datetime("2026-02-25T10:00:00")
        assert parsed is not None
        assert parsed.tzinfo == UTC

    def test_invalid_datetime_raises(self):
        with pytest.raises(CursorError):
            parse_cursor_datetime("not-a-datetime")


class TestCursorWithDifferentPayloads:
    def test_empty_dict(self):
        encoded = encode_cursor({})
        decoded = decode_cursor(encoded)
        assert decoded == {}

    def test_nested_values(self):
        payload = {"key": "value", "number": 42, "nested": {"a": 1}}
        encoded = encode_cursor(payload)
        decoded = decode_cursor(encoded)
        assert decoded == payload

    def test_unicode_values(self):
        payload = {"name": "Test Chat"}
        encoded = encode_cursor(payload)
        decoded = decode_cursor(encoded)
        assert decoded == payload
