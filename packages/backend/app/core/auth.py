import logging
from dataclasses import dataclass, field
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

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)
api_key_scheme = HTTPBearer(auto_error=False)

ALL_SCOPES = frozenset({"read", "write"})


@dataclass
class AuthContext:
    """Authentication context with user and permission scopes."""

    user: User
    scopes: set[str] = field(default_factory=lambda: {"read", "write"})
    auth_type: str = "jwt"

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


async def get_auth_context(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    api_key: Annotated[HTTPAuthorizationCredentials | None, Depends(api_key_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthContext:
    """Authenticate and return AuthContext with user + scopes."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Try JWT token first — full access
    if token:
        payload = decode_token(token)
        if payload and payload.get("type") == "access":
            user_id = payload.get("sub")
            if user_id:
                result = await db.execute(select(User).where(User.id == UUID(user_id)))
                user = result.scalar_one_or_none()
                if user:
                    return AuthContext(
                        user=user, scopes={"read", "write"}, auth_type="jwt"
                    )

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
                # Check expiration
                if (
                    api_key_record.expires_at
                    and api_key_record.expires_at < datetime.now(UTC)
                ):
                    logger.warning(
                        "Expired API key used: %s (expired %s)",
                        api_key_record.key_hint,
                        api_key_record.expires_at.isoformat(),
                    )
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="API key has expired",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                api_key_record.last_used_at = datetime.now(UTC)
                await db.flush()
                result = await db.execute(
                    select(User).where(User.id == api_key_record.user_id)
                )
                user = result.scalar_one_or_none()
                if user:
                    # Parse scopes from the stored comma-separated string
                    key_scopes = set(api_key_record.scopes.split(",")) & ALL_SCOPES
                    return AuthContext(
                        user=user,
                        scopes=key_scopes,
                        auth_type="api_key",
                    )

    raise credentials_exception


async def get_current_user(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> User:
    """Get current user (backward compatible — no scope check)."""
    return ctx.user


async def get_current_user_optional(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    api_key: Annotated[HTTPAuthorizationCredentials | None, Depends(api_key_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    try:
        ctx = await get_auth_context(token, api_key, db)
        return ctx.user
    except HTTPException:
        return None


def require_scope(scope: str):
    """FastAPI dependency factory: checks the auth context has the required scope."""

    async def _check(
        ctx: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> AuthContext:
        if scope not in ctx.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key lacks '{scope}' permission",
            )
        return ctx

    return _check


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]
RequireWrite = Annotated[AuthContext, Depends(require_scope("write"))]
