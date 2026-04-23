from unittest.mock import AsyncMock, patch
from uuid import uuid4

from telethon.errors import SessionRevokedError

from app.listener.main import TelegramListener


class TestTelegramListener:
    async def test_handle_unauthorized_client_invalidates_and_stops_user(self):
        listener = TelegramListener()
        listener.redis = AsyncMock()

        user_id = uuid4()
        client = AsyncMock()
        listener.clients[user_id] = client

        with patch(
            "app.listener.main.invalidate_client_authorization",
            new_callable=AsyncMock,
        ) as mock_invalidate:
            await listener._handle_unauthorized_client(
                user_id,
                client,
                SessionRevokedError(request=None),
            )

        mock_invalidate.assert_awaited_once()
        assert mock_invalidate.await_args.args[0] is client
        assert mock_invalidate.await_args.args[1] == user_id
        assert user_id not in listener.clients
        client.disconnect.assert_awaited_once()
        listener.redis.delete.assert_awaited_once_with(f"listener:active:{user_id}")
