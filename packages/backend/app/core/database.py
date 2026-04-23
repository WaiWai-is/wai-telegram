import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

_engine: AsyncEngine | None = None
_engine_pid: int | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _create_engine() -> AsyncEngine:
    return create_async_engine(
        settings.async_database_url,
        echo=settings.debug,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


def get_engine() -> AsyncEngine:
    global _engine, _engine_pid, _session_factory

    pid = os.getpid()
    if _engine is None or _engine_pid != pid:
        _engine = _create_engine()
        _session_factory = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        _engine_pid = pid

    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None or _engine_pid != os.getpid():
        get_engine()

    assert _session_factory is not None
    return _session_factory


class Base(DeclarativeBase):
    pass


async def dispose_engine() -> None:
    """Dispose the current process-local engine's connection pool."""
    global _engine, _engine_pid, _session_factory

    if _engine is not None and _engine_pid == os.getpid():
        await _engine.dispose()

    _engine = None
    _engine_pid = None
    _session_factory = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
