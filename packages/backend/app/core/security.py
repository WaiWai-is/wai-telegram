import secrets
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_fernet() -> Fernet:
    if not settings.encryption_key:
        raise ValueError("ENCRYPTION_KEY not configured")
    return Fernet(settings.encryption_key.encode())


def encrypt_session(session_string: str) -> str:
    fernet = get_fernet()
    return fernet.encrypt(session_string.encode()).decode()


def decrypt_session(encrypted_session: str) -> str:
    fernet = get_fernet()
    return fernet.decrypt(encrypted_session.encode()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def hash_api_key(api_key: str) -> str:
    return pwd_context.hash(api_key)


def verify_api_key(api_key: str, hashed_key: str) -> bool:
    return pwd_context.verify(api_key, hashed_key)


def generate_api_key() -> str:
    return f"wai_{secrets.token_urlsafe(32)}"


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except JWTError:
        return None
