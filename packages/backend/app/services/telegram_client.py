import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.sessions import StringSession

from app.core.config import get_settings
from app.core.security import decrypt_session, encrypt_session
from app.models.session import TelegramSession

logger = logging.getLogger(__name__)
settings = get_settings()

async def get_client(user_id: UUID, db: AsyncSession) -> TelegramClient:
    """Create a fresh Telegram client for a user.

    Clients are intentionally not cached globally to avoid cross-event-loop reuse.
    """
    result = await db.execute(
        select(TelegramSession).where(
            TelegramSession.user_id == user_id, TelegramSession.is_active == True
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise ValueError("No active Telegram session found")

    session_string = decrypt_session(session.session_string)
    client = TelegramClient(
        StringSession(session_string),
        settings.telegram_api_id,
        settings.telegram_api_hash,
        device_model=settings.telegram_device_model,
        system_version=settings.telegram_system_version,
        app_version=settings.telegram_app_version,
        flood_sleep_threshold=settings.telegram_flood_sleep_threshold,
        receive_updates=False,
    )
    await client.connect()
    return client


async def create_auth_client() -> TelegramClient:
    """Create a temporary client for authentication."""
    client = TelegramClient(
        StringSession(),
        settings.telegram_api_id,
        settings.telegram_api_hash,
        device_model=settings.telegram_device_model,
        system_version=settings.telegram_system_version,
        app_version=settings.telegram_app_version,
        flood_sleep_threshold=settings.telegram_flood_sleep_threshold,
        receive_updates=False,
    )
    await client.connect()
    return client


def _get_code_type_name(sent_code) -> str:
    """Extract human-readable code delivery type from SentCode result."""
    code_type = sent_code.type
    type_name = type(code_type).__name__
    type_map = {
        "SentCodeTypeApp": "app",
        "SentCodeTypeSms": "sms",
        "SentCodeTypeCall": "call",
        "SentCodeTypeFlashCall": "flash_call",
        "SentCodeTypeMissedCall": "missed_call",
        "SentCodeTypeEmailCode": "email",
        "SentCodeTypeFragmentSms": "fragment_sms",
    }
    return type_map.get(type_name, "unknown")


async def request_code(phone_number: str) -> tuple[TelegramClient, str, str]:
    """Request verification code for phone number.

    Returns (client, phone_code_hash, code_type).
    """
    client = await create_auth_client()
    try:
        result = await client.send_code_request(phone_number)
        code_type = _get_code_type_name(result)
        logger.info(
            f"Code requested for {phone_number}: type={code_type}, "
            f"timeout={getattr(result, 'timeout', None)}s"
        )
        return client, result.phone_code_hash, code_type
    except FloodWaitError as e:
        wait_time = int(e.seconds * settings.flood_wait_multiplier)
        logger.warning(f"FloodWait: need to wait {wait_time}s for {phone_number}")
        await client.disconnect()
        raise ValueError(f"Too many attempts. Please wait {wait_time} seconds.")
    except Exception:
        await client.disconnect()
        raise


async def verify_code(
    client: TelegramClient,
    phone_number: str,
    phone_code_hash: str,
    code: str,
    password: str | None = None,
) -> tuple[str, int]:
    """Verify code and complete authentication. Returns (session_string, telegram_user_id)."""
    try:
        await client.sign_in(
            phone=phone_number,
            code=code,
            phone_code_hash=phone_code_hash,
        )
    except SessionPasswordNeededError:
        if not password:
            raise ValueError("Two-factor authentication is enabled. Password required.")
        await client.sign_in(password=password)

    me = await client.get_me()
    session_string = client.session.save()
    return session_string, me.id


async def save_session(
    db: AsyncSession,
    user_id: UUID,
    phone_number: str,
    session_string: str,
    telegram_user_id: int,
) -> TelegramSession:
    """Save encrypted Telegram session to database."""
    # Ensure stale in-memory client for this user is not reused.
    await disconnect_client(user_id)

    # Deactivate any existing sessions for this user
    result = await db.execute(
        select(TelegramSession).where(
            TelegramSession.user_id == user_id, TelegramSession.is_active == True
        )
    )
    existing = result.scalars().all()
    for session in existing:
        session.is_active = False

    # Create new session
    encrypted_session = encrypt_session(session_string)
    new_session = TelegramSession(
        user_id=user_id,
        phone_number=phone_number,
        session_string=encrypted_session,
        telegram_user_id=telegram_user_id,
        is_active=True,
    )
    db.add(new_session)
    await db.flush()
    return new_session


async def disconnect_client(user_id: UUID) -> None:
    """Disconnect and remove a cached client if present.

    No-op because sync clients are now created per operation.
    """
    _ = user_id


async def delete_session(db: AsyncSession, user_id: UUID) -> None:
    """Delete user's Telegram session."""
    await disconnect_client(user_id)
    result = await db.execute(
        select(TelegramSession).where(TelegramSession.user_id == user_id)
    )
    sessions = result.scalars().all()
    for session in sessions:
        await db.delete(session)
