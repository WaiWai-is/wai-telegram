import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least 1 uppercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least 1 digit")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


# --- API Key schemas ---


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_in_days: int | None = Field(
        default=365,
        ge=1,
        le=3650,
        description="Key expiration in days (1-3650). Null for no expiration.",
    )


class ApiKeyResponse(BaseModel):
    id: UUID
    name: str
    key_hint: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None

    class Config:
        from_attributes = True


class ApiKeyCreateResponse(BaseModel):
    id: UUID
    name: str
    api_key: str
    key_hint: str
    expires_at: datetime | None
    message: str = "Store this API key securely. It won't be shown again."


class ApiKeyUpdateRequest(BaseModel):
    is_active: bool
