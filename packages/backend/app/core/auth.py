from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
    OAuth2PasswordBearer,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import compute_api_key_prefix, decode_token, verify_api_key
from app.models.api_key import ApiKey
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)
api_key_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    api_key: Annotated[HTTPAuthorizationCredentials | None, Depends(api_key_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Try JWT token first
    if token:
        payload = decode_token(token)
        if payload and payload.get("type") == "access":
            user_id = payload.get("sub")
            if user_id:
                result = await db.execute(select(User).where(User.id == UUID(user_id)))
                user = result.scalar_one_or_none()
                if user:
                    return user

    # Try API key via api_keys table
    if api_key and api_key.credentials.startswith("wai_"):
        prefix = compute_api_key_prefix(api_key.credentials)
        result = await db.execute(
            select(ApiKey).where(
                ApiKey.key_prefix == prefix,
                ApiKey.is_active == True,
            )
        )
        # Iterate candidates to handle (unlikely) prefix collisions
        for api_key_record in result.scalars().all():
            if verify_api_key(api_key.credentials, api_key_record.key_hash):
                api_key_record.last_used_at = datetime.now(UTC)
                await db.flush()
                result = await db.execute(
                    select(User).where(User.id == api_key_record.user_id)
                )
                user = result.scalar_one_or_none()
                if user:
                    return user

    raise credentials_exception


async def get_current_user_optional(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    api_key: Annotated[HTTPAuthorizationCredentials | None, Depends(api_key_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    try:
        return await get_current_user(token, api_key, db)
    except HTTPException:
        return None


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]
