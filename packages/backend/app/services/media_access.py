from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from app.core.config import get_settings

MEDIA_DOWNLOAD_TOKEN_TTL = timedelta(minutes=60)


@dataclass(frozen=True)
class MediaDownloadClaims:
    user_id: UUID
    chat_id: UUID
    telegram_message_id: int


def create_media_download_token(
    *,
    user_id: UUID,
    chat_id: UUID,
    telegram_message_id: int,
    expires_at: datetime | None = None,
) -> str:
    """Create a short-lived capability for one user's Telegram media item."""
    now = datetime.now(UTC)
    expiry = expires_at or (now + MEDIA_DOWNLOAD_TOKEN_TTL)
    payload = {
        "typ": "telegram-media",
        "sub": str(user_id),
        "chat_id": str(chat_id),
        "telegram_message_id": telegram_message_id,
        "iat": int(now.timestamp()),
        "exp": int(expiry.timestamp()),
    }
    return str(jwt.encode(payload, get_settings().secret_key, algorithm="HS256"))


def decode_media_download_token(token: str) -> MediaDownloadClaims:
    """Validate a media capability and return its narrow resource scope."""
    try:
        payload = jwt.decode(
            token,
            get_settings().secret_key,
            algorithms=["HS256"],
            options={
                "require": ["typ", "sub", "chat_id", "telegram_message_id", "exp"]
            },
        )
        if payload.get("typ") != "telegram-media":
            raise ValueError
        return MediaDownloadClaims(
            user_id=UUID(str(payload["sub"])),
            chat_id=UUID(str(payload["chat_id"])),
            telegram_message_id=int(payload["telegram_message_id"]),
        )
    except (
        jwt.InvalidTokenError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
    ) as exc:
        raise ValueError("invalid media download token") from exc
