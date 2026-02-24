from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "Telegram AI Message Manager"
    debug: bool = False
    environment: Literal["development", "staging", "production"] = "development"

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://telegram:telegram_dev@localhost:5432/telegram_ai"
    )

    # Redis
    redis_url: str = Field(default="redis://localhost:6379")

    # Security
    secret_key: str = Field(default="dev-secret-key-change-in-production")
    encryption_key: str = Field(default="")  # Fernet key for session encryption
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    algorithm: str = "HS256"

    # Rate limiting
    rate_limit_per_minute: int = 60

    # Telegram
    telegram_api_id: int = Field(default=0)
    telegram_api_hash: str = Field(default="")

    # OpenAI (embeddings)
    openai_api_key: str = Field(default="")
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    embedding_batch_size: int = 100

    # Anthropic (digests)
    anthropic_api_key: str = Field(default="")
    digest_model: str = "claude-sonnet-4-20250514"

    # Sync settings
    sync_batch_size: int = 100
    sync_delay_seconds: float = 1.0
    sync_delay_jitter: float = 0.5
    sync_progressive_delay_interval: int = 5  # Increase delay every N batches
    sync_progressive_delay_step: float = 0.5  # Add this much per interval
    sync_dialog_limit: int = 100
    flood_wait_multiplier: float = 1.2

    # Telegram client settings (anti-ban)
    telegram_device_model: str = "MacBook Pro"
    telegram_system_version: str = "macOS 14.5"
    telegram_app_version: str = "10.8.1"
    telegram_flood_sleep_threshold: int = 120

    # Rate budget tracking
    rate_budget_hourly: int = 200
    rate_budget_daily: int = 2000

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        """Ensure critical secrets are set outside local development."""
        if self.environment in {"staging", "production"}:
            if self.secret_key == "dev-secret-key-change-in-production":
                raise ValueError("SECRET_KEY must be set in staging/production")
            if not self.encryption_key:
                raise ValueError("ENCRYPTION_KEY must be set in staging/production")
            if not self.telegram_api_id or not self.telegram_api_hash:
                raise ValueError("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set")
        return self

    @computed_field
    @property
    def async_database_url(self) -> str:
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
