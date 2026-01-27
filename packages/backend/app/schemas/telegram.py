from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RequestCodeRequest(BaseModel):
    phone_number: str


class RequestCodeResponse(BaseModel):
    phone_code_hash: str
    message: str = "Verification code sent"


class VerifyCodeRequest(BaseModel):
    phone_number: str
    phone_code_hash: str
    code: str
    password: str | None = None  # For 2FA


class VerifyCodeResponse(BaseModel):
    success: bool
    telegram_user_id: int
    message: str = "Successfully authenticated with Telegram"


class SessionResponse(BaseModel):
    id: UUID
    phone_number: str
    telegram_user_id: int | None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
