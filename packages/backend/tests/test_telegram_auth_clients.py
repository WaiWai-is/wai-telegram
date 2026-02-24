import pytest

from app.api.v1.telegram import (
    _auth_clients,
    _pop_and_disconnect_auth_client,
    _replace_auth_client,
)


class DummyTelegramClient:
    def __init__(self) -> None:
        self.disconnected = False

    async def disconnect(self) -> None:
        self.disconnected = True


@pytest.mark.asyncio
async def test_replace_auth_client_disconnects_old_client() -> None:
    key = "test-user:+10000000000"
    old_client = DummyTelegramClient()
    new_client = DummyTelegramClient()
    _auth_clients.clear()
    _auth_clients[key] = (old_client, 0.0)

    await _replace_auth_client(key, new_client)

    assert old_client.disconnected is True
    assert _auth_clients[key][0] is new_client


@pytest.mark.asyncio
async def test_pop_auth_client_disconnects_and_removes() -> None:
    key = "test-user:+12223334444"
    client = DummyTelegramClient()
    _auth_clients.clear()
    _auth_clients[key] = (client, 0.0)

    await _pop_and_disconnect_auth_client(key)

    assert client.disconnected is True
    assert key not in _auth_clients
