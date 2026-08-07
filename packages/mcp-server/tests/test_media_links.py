from unittest.mock import AsyncMock, patch

import pytest
from mcp.types import ResourceLink
from telegram_wai_mcp import server


@pytest.mark.asyncio
async def test_get_message_content_returns_download_resource_link():
    mock_api = AsyncMock()
    mock_api.execute_data_tool.return_value = {
        "telegram_message_id": 42,
        "media_type": "audio",
        "media_file_name": "voice.ogg",
        "media_mime_type": "audio/ogg",
        "media_file_size": 321,
        "media_processing_status": "ready",
        "content_text": "Полная расшифровка",
        "telegram_message_url": "https://t.me/example/42",
        "media_download_url": "/api/v1/chats/chat-1/messages/42/media?token=short-lived",
    }

    with patch("telegram_wai_mcp.server.get_client", return_value=mock_api):
        result = await server.call_tool(
            "get_message_content",
            {"chat_id": "chat-1", "telegram_message_id": 42},
        )

    content = result.content if hasattr(result, "content") else result
    text = next(item.text for item in content if hasattr(item, "text"))
    assert "https://t.me/example/42" in text
    assert "https://telegram.waiwai.is/api/v1/chats/chat-1/messages/42/media" in text
    resource_links = [item for item in content if isinstance(item, ResourceLink)]
    assert len(resource_links) == 1
    assert str(resource_links[0].uri).startswith("https://telegram.waiwai.is/")
    assert resource_links[0].name == "voice.ogg"


@pytest.mark.asyncio
async def test_download_media_is_a_discoverable_mcp_tool():
    mock_api = AsyncMock()
    mock_api.execute_data_tool.return_value = {
        "telegram_message_id": 42,
        "media_type": "video",
        "media_file_name": "clip.mp4",
        "media_mime_type": "video/mp4",
        "media_download_url": "/api/v1/chats/chat-1/messages/42/media?token=short-lived",
    }

    with patch("telegram_wai_mcp.server.get_client", return_value=mock_api):
        result = await server.call_tool(
            "download_media",
            {"chat_id": "chat-1", "telegram_message_id": 42},
        )

    content = result.content if hasattr(result, "content") else result
    text = next(item.text for item in content if hasattr(item, "text"))
    assert "Download URL:" in text
    mock_api.execute_data_tool.assert_awaited_once_with(
        "download_media",
        {"chat_id": "chat-1", "telegram_message_id": 42},
    )

    discovery_api = AsyncMock()
    discovery_api.list_data_tools.return_value = {
        "tools": [
            {
                "name": "download_media",
                "description": "Get a short-lived original media link.",
                "parameters": {"type": "object", "properties": {}},
            }
        ]
    }
    with patch("telegram_wai_mcp.server.get_client", return_value=discovery_api):
        tools = await server.list_tools()
    download_tool = next(tool for tool in tools if tool.name == "download_media")
    assert "short-lived" in download_tool.description


def test_mcp_uses_public_origin_for_internal_backend(monkeypatch):
    api = AsyncMock()
    api.base_url = "http://127.0.0.1:8000"
    monkeypatch.setenv("TELEGRAM_AI_PUBLIC_URL", "https://telegram.waiwai.is")

    assert server._client_base_url(api) == "https://telegram.waiwai.is"
