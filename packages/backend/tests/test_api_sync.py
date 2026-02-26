from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.models.chat import ChatType, TelegramChat
from app.models.sync_job import SyncJob, SyncStatus


class TestSyncAll:
    async def test_sync_all_success(self, auth_client, db_session, test_user):
        mock_task = MagicMock()
        mock_task.delay = MagicMock()

        with (
            patch("app.api.v1.sync.sync_all_chats_task", mock_task),
            patch("app.api.v1.sync.redis_client", MagicMock()),
        ):
            response = await auth_client.post("/api/v1/sync/all")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "pending"
            mock_task.delay.assert_called_once()

    async def test_sync_all_conflict(self, auth_client, db_session, test_user):
        # Create an in-progress bulk job
        job = SyncJob(
            user_id=test_user.id,
            chat_id=None,
            status=SyncStatus.IN_PROGRESS,
            updated_at=datetime.now(UTC),
        )
        db_session.add(job)
        await db_session.flush()

        with patch(
            "app.api.v1.sync.redis_client", MagicMock(get=MagicMock(return_value=b"1"))
        ):
            response = await auth_client.post("/api/v1/sync/all")
            assert response.status_code == 409


class TestSyncChat:
    async def test_sync_chat_success(self, auth_client, db_session, test_user):
        chat = TelegramChat(
            user_id=test_user.id,
            telegram_chat_id=12345,
            chat_type=ChatType.PRIVATE,
            title="Sync Chat",
        )
        db_session.add(chat)
        await db_session.flush()

        mock_task = MagicMock()
        mock_task.delay = MagicMock()

        with (
            patch("app.api.v1.sync.sync_chat_task", mock_task),
            patch("app.api.v1.sync.redis_client", MagicMock()),
        ):
            response = await auth_client.post(f"/api/v1/sync/chats/{chat.id}")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "pending"

    async def test_sync_chat_not_found(self, auth_client):
        with patch("app.api.v1.sync.redis_client", MagicMock()):
            response = await auth_client.post(f"/api/v1/sync/chats/{uuid4()}")
            assert response.status_code == 404


class TestGetSyncProgress:
    async def test_get_progress_success(self, auth_client, db_session, test_user):
        chat = TelegramChat(
            user_id=test_user.id,
            telegram_chat_id=12345,
            chat_type=ChatType.PRIVATE,
            title="Progress Chat",
        )
        db_session.add(chat)
        await db_session.flush()

        job = SyncJob(
            user_id=test_user.id,
            chat_id=chat.id,
            status=SyncStatus.COMPLETED,
            messages_processed=50,
        )
        db_session.add(job)
        await db_session.flush()

        mock_redis = MagicMock()
        mock_redis.get = MagicMock(return_value=None)

        with patch("app.api.v1.sync.redis_client", mock_redis):
            response = await auth_client.get(f"/api/v1/sync/jobs/{job.id}")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "completed"
            assert data["messages_processed"] == 50

    async def test_get_progress_not_found(self, auth_client):
        with patch("app.api.v1.sync.redis_client", MagicMock()):
            response = await auth_client.get(f"/api/v1/sync/jobs/{uuid4()}")
            assert response.status_code == 404


class TestListSyncJobs:
    async def test_list_jobs(self, auth_client, db_session, test_user):
        job = SyncJob(
            user_id=test_user.id,
            status=SyncStatus.COMPLETED,
            messages_processed=100,
        )
        db_session.add(job)
        await db_session.flush()

        response = await auth_client.get("/api/v1/sync/jobs")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
