import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


class TestSettingsDefaults:
    def test_default_environment(self):
        s = Settings()
        assert s.environment == "development"

    def test_default_debug(self):
        s = Settings()
        assert s.debug is False

    def test_default_token_expiry(self):
        s = Settings()
        assert s.access_token_expire_minutes == 15
        assert s.refresh_token_expire_days == 7

    def test_default_algorithm(self):
        s = Settings()
        assert s.algorithm == "HS256"

    def test_async_database_url_matches_database_url(self):
        s = Settings()
        assert s.async_database_url == s.database_url


class TestProductionValidation:
    def test_staging_requires_secret_key(self):
        with pytest.raises(ValidationError, match="SECRET_KEY"):
            Settings(environment="staging")

    def test_production_requires_encryption_key(self):
        with pytest.raises(ValidationError, match="ENCRYPTION_KEY"):
            Settings(
                environment="production",
                secret_key="real-secret-key",
            )

    def test_production_requires_telegram_api(self):
        with pytest.raises(ValidationError, match="TELEGRAM_API"):
            Settings(
                environment="production",
                secret_key="real-secret-key",
                encryption_key="real-encryption-key",
            )

    def test_development_allows_defaults(self):
        s = Settings(environment="development")
        assert s.secret_key == "dev-secret-key-change-in-production"


class TestGetSettingsCached:
    def test_returns_settings_instance(self):
        get_settings.cache_clear()
        s = get_settings()
        assert isinstance(s, Settings)

    def test_returns_same_instance(self):
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_cache_clear_creates_new_instance(self):
        get_settings.cache_clear()
        s1 = get_settings()
        get_settings.cache_clear()
        s2 = get_settings()
        assert s1 is not s2
