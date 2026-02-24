from app.api.v1.sync import _parse_retry_after_seconds


def test_parse_retry_after_seconds_present() -> None:
    assert _parse_retry_after_seconds("rate_limited: retry_after_seconds=42") == 42


def test_parse_retry_after_seconds_absent() -> None:
    assert _parse_retry_after_seconds("generic failure") is None
