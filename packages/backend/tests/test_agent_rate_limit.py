"""Tests for bot rate limiter."""

from app.services.agent.rate_limit import (
    MINUTE_LIMIT,
    check_rate_limit,
    clear_rate_limits,
    get_rate_limit_message,
)


class TestRateLimit:
    def setup_method(self):
        clear_rate_limits()

    def test_allows_normal_usage(self):
        assert check_rate_limit(123) is True

    def test_allows_up_to_minute_limit(self):
        for _ in range(MINUTE_LIMIT - 1):
            assert check_rate_limit(456) is True

    def test_blocks_after_minute_limit(self):
        for _ in range(MINUTE_LIMIT):
            check_rate_limit(789)
        assert check_rate_limit(789) is False

    def test_different_users_independent(self):
        for _ in range(MINUTE_LIMIT):
            check_rate_limit(111)
        assert check_rate_limit(111) is False
        assert check_rate_limit(222) is True

    def test_clear_resets(self):
        for _ in range(MINUTE_LIMIT):
            check_rate_limit(333)
        clear_rate_limits()
        assert check_rate_limit(333) is True


class TestRateLimitMessage:
    def test_english(self):
        msg = get_rate_limit_message("en")
        assert "Too many" in msg

    def test_russian(self):
        msg = get_rate_limit_message("ru")
        assert "Слишком" in msg
