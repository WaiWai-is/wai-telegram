from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token, verify_api_key
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

    # Try API key
    if api_key and api_key.credentials.startswith("wai_"):
        # Find user by checking API key hash
        result = await db.execute(select(User).where(User.api_key_hash.isnot(None)))
        users = result.scalars().all()
        for user in users:
            if user.api_key_hash and verify_api_key(api_key.credentials, user.api_key_hash):
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
