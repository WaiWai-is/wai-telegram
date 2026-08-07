"""Tests for the closed single-user Telegram resolver."""

from sqlalchemy import func, select

from app.models.session import TelegramSession
from app.models.user import User
from app.services.agent.user_resolver import _cache, clear_cache


class TestUserResolverCache:
    def setup_method(self):
        clear_cache()

    def test_cache_starts_empty(self):
        assert len(_cache) == 0

    def test_clear_cache(self):
        from uuid import uuid4

        _cache[12345] = uuid4()
        assert len(_cache) == 1
        clear_cache()
        assert len(_cache) == 0

    def test_cache_stores_mapping(self):
        from uuid import uuid4

        uid = uuid4()
        _cache[99999] = uid
        assert _cache[99999] == uid

    def test_multiple_users_isolated(self):
        from uuid import uuid4

        uid1 = uuid4()
        uid2 = uuid4()
        _cache[111] = uid1
        _cache[222] = uid2
        assert _cache[111] == uid1
        assert _cache[222] == uid2
        assert _cache[111] != _cache[222]


class TestUserResolverDatabase:
    async def test_active_owner_session_resolves(self, db_session, test_user):
        session = TelegramSession(
            user_id=test_user.id,
            phone_number="+10000000000",
            session_string="encrypted",
            telegram_user_id=777,
            is_active=True,
        )
        db_session.add(session)
        await db_session.flush()

        from app.services.agent.user_resolver import resolve_user_id

        assert await resolve_user_id(db_session, 777) == test_user.id

    async def test_unknown_sender_is_not_created(self, db_session):
        before = (
            await db_session.execute(select(func.count()).select_from(User))
        ).scalar_one()

        from app.services.agent.user_resolver import resolve_user_id

        assert await resolve_user_id(db_session, 999_999) is None
        after = (
            await db_session.execute(select(func.count()).select_from(User))
        ).scalar_one()
        assert after == before

    async def test_inactive_user_session_is_rejected(self, db_session, test_user):
        test_user.is_active = False
        db_session.add(
            TelegramSession(
                user_id=test_user.id,
                phone_number="+10000000000",
                session_string="encrypted",
                telegram_user_id=888,
                is_active=True,
            )
        )
        await db_session.flush()

        from app.services.agent.user_resolver import resolve_user_id

        assert await resolve_user_id(db_session, 888) is None
