import pytest
from app.schemas.settings import UserSettingsUpdate
from pydantic import ValidationError


class TestUserSettingsUpdate:
    def test_all_none_is_valid(self):
        update = UserSettingsUpdate()
        assert update.digest_enabled is None
        assert update.digest_hour_utc is None

    def test_partial_update(self):
        update = UserSettingsUpdate(digest_enabled=False)
        assert update.digest_enabled is False
        assert update.digest_hour_utc is None

    def test_valid_timezone_iana(self):
        update = UserSettingsUpdate(digest_timezone="America/New_York")
        assert update.digest_timezone == "America/New_York"

    def test_valid_timezone_utc(self):
        update = UserSettingsUpdate(digest_timezone="UTC")
        assert update.digest_timezone == "UTC"

    def test_invalid_timezone_rejected(self):
        with pytest.raises(ValidationError, match="Invalid IANA timezone"):
            UserSettingsUpdate(digest_timezone="Not/A Valid-Zone!")

    def test_hour_range_min(self):
        update = UserSettingsUpdate(digest_hour_utc=0)
        assert update.digest_hour_utc == 0

    def test_hour_range_max(self):
        update = UserSettingsUpdate(digest_hour_utc=23)
        assert update.digest_hour_utc == 23

    def test_hour_below_range_rejected(self):
        with pytest.raises(ValidationError):
            UserSettingsUpdate(digest_hour_utc=-1)

    def test_hour_above_range_rejected(self):
        with pytest.raises(ValidationError):
            UserSettingsUpdate(digest_hour_utc=24)

    def test_realtime_sync_toggle(self):
        update = UserSettingsUpdate(realtime_sync_enabled=True)
        assert update.realtime_sync_enabled is True
