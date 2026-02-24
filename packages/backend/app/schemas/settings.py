from pydantic import BaseModel, Field


class UserSettingsResponse(BaseModel):
    digest_enabled: bool
    digest_hour_utc: int
    digest_telegram_enabled: bool
    auto_sync_enabled: bool
    auto_sync_interval_minutes: int
    realtime_sync_enabled: bool
    listener_active: bool

    model_config = {"from_attributes": True}


class UserSettingsUpdate(BaseModel):
    digest_enabled: bool | None = None
    digest_hour_utc: int | None = Field(default=None, ge=0, le=23)
    digest_telegram_enabled: bool | None = None
    auto_sync_enabled: bool | None = None
    auto_sync_interval_minutes: int | None = Field(
        default=None, description="Must be one of: 15, 60, 360, 720, 1440"
    )
    realtime_sync_enabled: bool | None = None


class TestBotResponse(BaseModel):
    success: bool
    message: str
