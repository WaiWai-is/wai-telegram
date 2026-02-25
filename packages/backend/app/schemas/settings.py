import re

from pydantic import BaseModel, Field, field_validator


class UserSettingsResponse(BaseModel):
    digest_enabled: bool
    digest_hour_utc: int
    digest_timezone: str
    digest_telegram_enabled: bool
    realtime_sync_enabled: bool
    listener_active: bool

    model_config = {"from_attributes": True}


class UserSettingsUpdate(BaseModel):
    digest_enabled: bool | None = None
    digest_hour_utc: int | None = Field(default=None, ge=0, le=23)
    digest_timezone: str | None = None
    digest_telegram_enabled: bool | None = None
    realtime_sync_enabled: bool | None = None

    @field_validator("digest_timezone")
    @classmethod
    def validate_timezone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r"^(UTC|[A-Za-z_]+/[A-Za-z_/\-]+)$", v):
            raise ValueError("Invalid IANA timezone format")
        return v


class TestBotResponse(BaseModel):
    success: bool
    message: str
