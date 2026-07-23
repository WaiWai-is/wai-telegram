import os

# Set test env BEFORE importing any app modules
os.environ["ENVIRONMENT"] = "development"
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["ENCRYPTION_KEY"] = "sZEBNdB1PTJZ8o9vGjJsXnUN9cQXz94O1jSWv7l4hQw="
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost:5432/test_db"
os.environ["REDIS_URL"] = "redis://localhost:6379"

from datetime import UTC, datetime
from uuid import uuid4

import fakeredis
import pytest
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.models.user import User
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
def clear_settings_cache():
    """Clear settings LRU cache before each test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _patch_columns_for_sqlite():
    """Patch PostgreSQL-specific column types for SQLite compatibility.

    Returns a list of (column, original_type) tuples to restore later.
    """
    from app.models.digest import DailyDigest
    from app.models.message import MessageContentChunk, TelegramMessage

    patches = []

    # Patch Vector -> String on TelegramMessage.embedding
    for model in (TelegramMessage, MessageContentChunk):
        embedding_col = model.__table__.columns.get("embedding")
        if embedding_col is not None:
            patches.append((embedding_col, embedding_col.type))
            embedding_col.type = String()

    # Patch JSONB -> JSON on DailyDigest.summary_stats
    stats_col = DailyDigest.__table__.columns.get("summary_stats")
    if stats_col is not None:
        patches.append((stats_col, stats_col.type))
        stats_col.type = JSON()

    return patches


def _unpatch_columns(patches):
    """Restore original column types after SQLite table creation."""
    for col, original_type in patches:
        col.type = original_type


def _remove_hnsw_indexes():
    """Remove PostgreSQL HNSW indexes while SQLite test tables are created.

    Returns the original table args and indexes so they can be restored.
    """
    from app.models.message import MessageContentChunk, TelegramMessage

    states = []
    for model in (TelegramMessage, MessageContentChunk):
        original_args = model.__table_args__
        filtered = tuple(
            arg
            for arg in original_args
            if not (
                hasattr(arg, "dialect_options")
                and "postgresql_using" in arg.dialect_options.get("postgresql", {})
            )
        )
        model.__table_args__ = filtered
        hnsw_indexes = [
            idx
            for idx in model.__table__.indexes
            if "postgresql_using" in idx.dialect_options.get("postgresql", {})
        ]
        for idx in hnsw_indexes:
            model.__table__.indexes.discard(idx)
        states.append((model, original_args, hnsw_indexes))
    return states


def _restore_hnsw_indexes(states):
    """Restore HNSW indexes after SQLite table creation."""
    for model, original_args, removed_indexes in states:
        model.__table_args__ = original_args
        for idx in removed_indexes:
            model.__table__.indexes.add(idx)


@pytest.fixture
async def async_engine():
    """Create SQLite in-memory engine for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # Patch PG-specific types and indexes for SQLite
    col_patches = _patch_columns_for_sqlite()
    hnsw_states = _remove_hnsw_indexes()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

    # Restore original types and indexes
    _unpatch_columns(col_patches)
    _restore_hnsw_indexes(hnsw_states)


@pytest.fixture
async def db_session(async_engine):
    """Create a transactional DB session for testing."""
    session_factory = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def fake_redis():
    """Create a fakeredis instance."""
    return fakeredis.FakeRedis()


@pytest.fixture
def fake_redis_decoded():
    """Create a fakeredis instance with decode_responses=True."""
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
async def test_user(db_session):
    """Create a test user in the database."""
    user = User(
        id=uuid4(),
        email="test@example.com",
        password_hash=hash_password("TestPassword1"),
        created_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
def test_user_token(test_user):
    """Create a JWT access token for the test user."""
    return create_access_token({"sub": str(test_user.id)})


@pytest.fixture
async def app(async_engine, db_session):
    """Create a FastAPI app with test overrides."""
    from app.core.limiter import limiter
    from app.main import app as fastapi_app

    async def override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    limiter.enabled = False

    yield fastapi_app

    fastapi_app.dependency_overrides.clear()
    limiter.enabled = True


@pytest.fixture
async def client(app):
    """Create an httpx AsyncClient for testing."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
async def auth_client(app, test_user_token):
    """Create an authenticated httpx AsyncClient."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {test_user_token}"},
    ) as ac:
        yield ac
