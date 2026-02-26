from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


class TestGenerateDigest:
    async def test_generate_no_messages(self, db_session, test_user):
        from app.services.digest_service import generate_digest

        digest = await generate_digest(db_session, test_user.id, date(2024, 1, 15))
        assert digest.content == "No messages to summarize for this day."
        assert digest.summary_stats["total_messages"] == 0

    async def test_generate_returns_cached(self, db_session, test_user):
        from app.models.digest import DailyDigest
        from app.services.digest_service import generate_digest

        existing = DailyDigest(
            user_id=test_user.id,
            digest_date=date(2024, 2, 20),
            content="Cached digest",
            summary_stats={"total_messages": 5},
        )
        db_session.add(existing)
        await db_session.flush()

        result = await generate_digest(db_session, test_user.id, date(2024, 2, 20))
        assert result.content == "Cached digest"


class TestGetDigest:
    async def test_exists(self, db_session, test_user):
        from app.models.digest import DailyDigest
        from app.services.digest_service import get_digest

        digest = DailyDigest(
            user_id=test_user.id,
            digest_date=date(2024, 3, 1),
            content="March digest",
            summary_stats={},
        )
        db_session.add(digest)
        await db_session.flush()

        result = await get_digest(db_session, test_user.id, date(2024, 3, 1))
        assert result is not None
        assert result.content == "March digest"

    async def test_not_found(self, db_session, test_user):
        from app.services.digest_service import get_digest

        result = await get_digest(db_session, test_user.id, date(2099, 1, 1))
        assert result is None


class TestGetDigests:
    async def test_ordered_list(self, db_session, test_user):
        from app.models.digest import DailyDigest
        from app.services.digest_service import get_digests

        for day in [1, 2, 3]:
            d = DailyDigest(
                user_id=test_user.id,
                digest_date=date(2024, 4, day),
                content=f"Digest {day}",
                summary_stats={},
            )
            db_session.add(d)
        await db_session.flush()

        results = await get_digests(db_session, test_user.id, limit=10)
        assert len(results) == 3
        # Should be ordered descending by date
        dates = [d.digest_date for d in results]
        assert dates == sorted(dates, reverse=True)
