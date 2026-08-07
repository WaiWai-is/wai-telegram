from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.cli.bot_api_cutover import configure_local_bot_api
from app.services.telegram_bot_api import TelegramBotAPIClient
from app.services.telegram_bot_api import TelegramBotAPIError


async def test_local_bot_api_copies_large_file_without_application_limit(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "app.services.telegram_bot_api.settings.telegram_bot_token",
        "test-token",
    )
    source = tmp_path / "bot-api" / "large.bin"
    source.parent.mkdir()
    source.write_bytes(b"x" * (21 * 1024 * 1024))
    destination = tmp_path / "download" / "large.bin"
    client = TelegramBotAPIClient()

    with patch.object(
        client,
        "get_file",
        new_callable=AsyncMock,
        return_value={"file_path": str(source), "file_size": source.stat().st_size},
    ):
        result = await client.download_file_to("large-file", destination)

    assert result.stat().st_size == 21 * 1024 * 1024
    assert result.read_bytes()[:4] == b"xxxx"


async def test_get_file_has_no_total_timeout(monkeypatch):
    monkeypatch.setattr(
        "app.services.telegram_bot_api.settings.telegram_bot_token",
        "test-token",
    )
    client = TelegramBotAPIClient()
    with patch.object(
        client,
        "call",
        new_callable=AsyncMock,
        return_value={"file_path": "/tmp/file"},
    ) as call:
        await client.get_file("large-file")

    call.assert_awaited_once_with(
        "getFile", params={"file_id": "large-file"}, timeout=None
    )


def test_bot_api_transport_has_no_cloud_fallback(monkeypatch):
    monkeypatch.setattr(
        "app.services.telegram_bot_api.settings.telegram_bot_token",
        "test-token",
    )
    client = TelegramBotAPIClient()
    assert client.base_url.startswith("http://127.0.0.1:")
    assert "api.telegram.org" not in client._method_url("getMe")


async def test_verify_local_never_calls_cloud_when_local_api_is_down():
    local = SimpleNamespace(
        call=AsyncMock(side_effect=TelegramBotAPIError("local unavailable"))
    )
    with (
        patch(
            "app.cli.bot_api_cutover.get_settings",
            return_value=SimpleNamespace(telegram_bot_token="test-token"),
        ),
        patch(
            "app.cli.bot_api_cutover.TelegramBotAPIClient",
            return_value=local,
        ),
        patch(
            "app.cli.bot_api_cutover._cloud_call",
            new_callable=AsyncMock,
        ) as cloud_call,
        pytest.raises(RuntimeError, match="cloud fallback is disabled"),
    ):
        await configure_local_bot_api(
            "https://telegram.waiwai.is",
            allow_cloud_logout=False,
        )

    cloud_call.assert_not_awaited()
