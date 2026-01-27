from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


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
    has_api_key: bool

    class Config:
        from_attributes = True


class ApiKeyResponse(BaseModel):
    api_key: str
    message: str = "Store this API key securely. It won't be shown again."
