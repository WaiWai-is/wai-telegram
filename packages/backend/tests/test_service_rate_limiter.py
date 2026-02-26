from unittest.mock import MagicMock, patch

from app.services.rate_limiter import check_budget, get_budget_status, record_request


class TestRecordRequest:
    def test_increments_counters(self):
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe

        with patch("app.services.rate_limiter._get_redis", return_value=mock_redis):
            record_request()
            assert mock_pipe.incr.call_count == 2
            mock_pipe.execute.assert_called_once()


class TestGetBudgetStatus:
    def test_zero_usage(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        with patch("app.services.rate_limiter._get_redis", return_value=mock_redis):
            status = get_budget_status()
            assert status["hourly_used"] == 0
            assert status["daily_used"] == 0
            assert status["hourly_remaining"] > 0
            assert status["daily_remaining"] > 0

    def test_with_usage(self):
        mock_redis = MagicMock()
        mock_redis.get.side_effect = lambda key: b"50" if "hourly" in key else b"100"

        with patch("app.services.rate_limiter._get_redis", return_value=mock_redis):
            status = get_budget_status()
            assert status["hourly_used"] == 50
            assert status["daily_used"] == 100


class TestCheckBudget:
    def test_within_budget(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = b"10"

        with patch("app.services.rate_limiter._get_redis", return_value=mock_redis):
            assert check_budget() is True

    def test_hourly_exhausted(self):
        mock_redis = MagicMock()
        mock_redis.get.side_effect = lambda key: b"999" if "hourly" in key else b"10"

        with (
            patch("app.services.rate_limiter._get_redis", return_value=mock_redis),
            patch("app.services.rate_limiter.settings") as mock_settings,
        ):
            mock_settings.rate_budget_hourly = 200
            mock_settings.rate_budget_daily = 2000
            assert check_budget() is False

    def test_daily_exhausted(self):
        mock_redis = MagicMock()
        mock_redis.get.side_effect = lambda key: b"10" if "hourly" in key else b"9999"

        with (
            patch("app.services.rate_limiter._get_redis", return_value=mock_redis),
            patch("app.services.rate_limiter.settings") as mock_settings,
        ):
            mock_settings.rate_budget_hourly = 200
            mock_settings.rate_budget_daily = 2000
            assert check_budget() is False
