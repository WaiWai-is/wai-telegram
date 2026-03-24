"""Tests for User Resolver — maps Telegram IDs to internal users."""

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
