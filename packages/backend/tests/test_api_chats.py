from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.models.chat import ChatType, TelegramChat
from app.models.message import MediaProcessingStatus, TelegramMessage
from app.services.telegram_client import TelegramSessionUnauthorizedError


class TestListChats:
    async def test_empty_list(self, auth_client):
        response = await auth_client.get("/api/v1/chats")
        assert response.status_code == 200
        data = response.json()
        assert data["chats"] == []
        assert data["total"] == 0

    async def test_with_chats(self, auth_client, db_session, test_user):
        chat = TelegramChat(
            user_id=test_user.id,
            telegram_chat_id=12345,
            chat_type=ChatType.PRIVATE,
            title="Test Chat",
            last_activity_at=datetime.now(UTC),
        )
        db_session.add(chat)
        await db_session.flush()

        response = await auth_client.get("/api/v1/chats")
        assert response.status_code == 200
        data = response.json()
        assert len(data["chats"]) == 1
        assert data["chats"][0]["title"] == "Test Chat"
        assert data["total"] == 1

    async def test_type_filter(self, auth_client, db_session, test_user):
        private_chat = TelegramChat(
            user_id=test_user.id,
            telegram_chat_id=111,
            chat_type=ChatType.PRIVATE,
            title="Private",
        )
        group_chat = TelegramChat(
            user_id=test_user.id,
            telegram_chat_id=222,
            chat_type=ChatType.GROUP,
            title="Group",
        )
        db_session.add_all([private_chat, group_chat])
        await db_session.flush()

        response = await auth_client.get("/api/v1/chats?chat_type=private")
        assert response.status_code == 200
        data = response.json()
        assert len(data["chats"]) == 1
        assert data["chats"][0]["title"] == "Private"

    async def test_unauthenticated(self, client):
        response = await client.get("/api/v1/chats")
        assert response.status_code == 401


class TestGetChat:
    async def test_get_chat_success(self, auth_client, db_session, test_user):
        chat = TelegramChat(
            user_id=test_user.id,
            telegram_chat_id=12345,
            chat_type=ChatType.PRIVATE,
            title="My Chat",
        )
        db_session.add(chat)
        await db_session.flush()

        response = await auth_client.get(f"/api/v1/chats/{chat.id}")
        assert response.status_code == 200
        assert response.json()["title"] == "My Chat"

    async def test_get_chat_not_found(self, auth_client):
        response = await auth_client.get(f"/api/v1/chats/{uuid4()}")
        assert response.status_code == 404

    async def test_get_other_users_chat(self, auth_client, db_session):
        other_user_id = uuid4()
        chat = TelegramChat(
            user_id=other_user_id,
            telegram_chat_id=99999,
            chat_type=ChatType.PRIVATE,
            title="Other User Chat",
        )
        db_session.add(chat)
        await db_session.flush()

        response = await auth_client.get(f"/api/v1/chats/{chat.id}")
        assert response.status_code == 404


class TestGetChatMessages:
    async def test_messages_success(self, auth_client, db_session, test_user):
        chat = TelegramChat(
            user_id=test_user.id,
            telegram_chat_id=12345,
            chat_type=ChatType.PRIVATE,
            title="Chat with Messages",
        )
        db_session.add(chat)
        await db_session.flush()

        msg = TelegramMessage(
            chat_id=chat.id,
            telegram_message_id=1,
            text="Hello world",
            has_media=False,
            sender_id=12345,
            sender_name="Test",
            is_outgoing=False,
            sent_at=datetime.now(UTC),
        )
        db_session.add(msg)
        await db_session.flush()

        response = await auth_client.get(f"/api/v1/chats/{chat.id}/messages")
        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) == 1
        assert data["messages"][0]["text"] == "Hello world"

    async def test_messages_chat_not_found(self, auth_client):
        response = await auth_client.get(f"/api/v1/chats/{uuid4()}/messages")
        assert response.status_code == 404


class TestGetMessageContent:
    async def test_returns_full_media_content(
        self,
        auth_client,
        db_session,
        test_user,
    ):
        chat = TelegramChat(
            user_id=test_user.id,
            telegram_chat_id=54321,
            chat_type=ChatType.PRIVATE,
            title="Media chat",
        )
        db_session.add(chat)
        await db_session.flush()
        message = TelegramMessage(
            chat_id=chat.id,
            telegram_message_id=42,
            text="Исходная подпись",
            has_media=True,
            media_type="video",
            content_text="Полная расшифровка",
            content_summary="Краткое резюме",
            media_processing_status=MediaProcessingStatus.READY,
            sender_id=1,
            is_outgoing=False,
            sent_at=datetime.now(UTC),
        )
        db_session.add(message)
        await db_session.flush()

        response = await auth_client.get(f"/api/v1/chats/{chat.id}/messages/42/content")

        assert response.status_code == 200
        payload = response.json()
        assert payload["text"] == "Исходная подпись"
        assert payload["content_text"] == "Полная расшифровка"
        assert payload["content_summary"] == "Краткое резюме"
        assert payload["media_processing_status"] == "ready"

    async def test_does_not_expose_another_users_content(
        self,
        auth_client,
        db_session,
    ):
        other_chat = TelegramChat(
            user_id=uuid4(),
            telegram_chat_id=98765,
            chat_type=ChatType.PRIVATE,
            title="Private",
        )
        db_session.add(other_chat)
        await db_session.flush()
        message = TelegramMessage(
            chat_id=other_chat.id,
            telegram_message_id=7,
            text=None,
            has_media=True,
            media_type="document",
            content_text="Secret",
            content_summary="Secret summary",
            media_processing_status=MediaProcessingStatus.READY,
            is_outgoing=False,
            sent_at=datetime.now(UTC),
        )
        db_session.add(message)
        await db_session.flush()

        response = await auth_client.get(
            f"/api/v1/chats/{other_chat.id}/messages/7/content"
        )

        assert response.status_code == 404


class TestRefreshChats:
    async def test_refresh_chats(self, auth_client):
        with patch(
            "app.api.v1.chats.sync_chats",
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = await auth_client.post("/api/v1/chats/refresh")
            assert response.status_code == 200
            data = response.json()
            assert data["chats"] == []

    async def test_refresh_chats_expired_session_returns_400(self, auth_client):
        with patch(
            "app.api.v1.chats.sync_chats",
            new_callable=AsyncMock,
            side_effect=TelegramSessionUnauthorizedError(
                "Telegram session expired. Reconnect Telegram and try again."
            ),
        ):
            response = await auth_client.post("/api/v1/chats/refresh")
        assert response.status_code == 400
        assert "Reconnect Telegram" in response.json()["detail"]
