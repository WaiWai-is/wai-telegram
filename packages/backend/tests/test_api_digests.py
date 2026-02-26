from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.models.digest import DailyDigest


class TestListDigests:
    async def test_list_empty(self, auth_client):
        response = await auth_client.get("/api/v1/digests")
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_with_data(self, auth_client, db_session, test_user):
        digest = DailyDigest(
            user_id=test_user.id,
            digest_date=date(2024, 1, 15),
            content="Test digest content",
            summary_stats={"total_messages": 10},
        )
        db_session.add(digest)
        await db_session.flush()

        response = await auth_client.get("/api/v1/digests")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["content"] == "Test digest content"


class TestGetDigestByDate:
    async def test_get_by_date_success(self, auth_client, db_session, test_user):
        digest = DailyDigest(
            user_id=test_user.id,
            digest_date=date(2024, 6, 15),
            content="June 15 digest",
            summary_stats={},
        )
        db_session.add(digest)
        await db_session.flush()

        response = await auth_client.get("/api/v1/digests/2024-06-15")
        assert response.status_code == 200
        assert response.json()["content"] == "June 15 digest"

    async def test_get_by_date_not_found(self, auth_client):
        response = await auth_client.get("/api/v1/digests/2099-01-01")
        assert response.status_code == 404


class TestGenerateDigest:
    async def test_generate_success(self, auth_client, db_session, test_user):
        digest = DailyDigest(
            id=uuid4(),
            user_id=test_user.id,
            digest_date=date.today(),
            content="Generated digest",
            summary_stats={"total_messages": 5},
            created_at=datetime.now(UTC),
        )
        with patch(
            "app.api.v1.digests.generate_digest",
            new_callable=AsyncMock,
            return_value=digest,
        ):
            response = await auth_client.post("/api/v1/digests/generate")
            assert response.status_code == 200
            data = response.json()
            assert data["content"] == "Generated digest"

    async def test_generate_unauthenticated(self, client):
        response = await client.post("/api/v1/digests/generate")
        assert response.status_code == 401
