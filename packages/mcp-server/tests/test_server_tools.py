from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from mcp.types import CallToolResult
from telegram_wai_mcp import server


class TestToolList:
    @pytest.mark.asyncio
    async def test_list_tools_returns_expected_tools(self):
        tools = await server.list_tools()
        tool_names = {t.name for t in tools}
        expected_tools = {
            "get_data_status",
            "search_messages",
            "list_chats",
            "get_chat_messages",
            "sync_chat",
            "get_sync_status",
            "get_daily_digest",
        }
        assert expected_tools.issubset(tool_names)

    @pytest.mark.asyncio
    async def test_each_tool_has_description(self):
        tools = await server.list_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name} has no description"

    @pytest.mark.asyncio
    async def test_each_tool_has_input_schema(self):
        tools = await server.list_tools()
        for tool in tools:
            assert tool.inputSchema, f"Tool {tool.name} has no input schema"


class TestCallTool:
    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        result = await server.call_tool("nonexistent_tool", {})
        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert len(result.content) == 1
        assert "Unknown tool" in result.content[0].text

    @pytest.mark.asyncio
    async def test_search_messages_requires_query(self):
        result = await server.call_tool("search_messages", {"query": ""})
        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert len(result.content) == 1
        assert "non-empty" in result.content[0].text.lower()

    @pytest.mark.asyncio
    async def test_send_message_surfaces_backend_errors_as_mcp_errors(self):
        mock_api = AsyncMock()
        mock_api.send_message.side_effect = RuntimeError(
            "Backend returned HTTP 400 for POST /api/v1/messages/chat/send: Telegram error"
        )

        with patch("telegram_wai_mcp.server.get_client", return_value=mock_api):
            result = await server.call_tool(
                "send_message",
                {"chat_id": "chat-123", "text": "hello"},
            )

        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert "Backend returned HTTP 400" in result.content[0].text
        mock_api.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_data_status_paginates_all_chats(self):
        mock_api = AsyncMock()
        page_1 = {
            "chats": [
                {
                    "title": f"Chat {i}",
                    "id": f"id-{i}",
                    "chat_type": "private",
                    "total_messages_synced": 1,
                    "last_sync_at": "2026-04-01T00:00:00+00:00",
                }
                for i in range(1, 201)
            ],
            "total": 250,
            "next_cursor": "cursor-2",
        }
        page_2 = {
            "chats": [
                {
                    "title": f"Chat {i}",
                    "id": f"id-{i}",
                    "chat_type": "private",
                    "total_messages_synced": 1,
                    "last_sync_at": "2026-04-01T00:00:00+00:00",
                }
                for i in range(201, 251)
            ],
            "total": 250,
            "next_cursor": None,
        }
        mock_api.get_settings.return_value = {
            "listener_active": True,
            "realtime_sync_enabled": True,
        }
        mock_api.list_chats.side_effect = [page_1, page_2]

        with patch("telegram_wai_mcp.server.get_client", return_value=mock_api):
            result = await server.call_tool("get_data_status", {})

        assert "Total chats: 250" in result[0].text
        assert "Total messages synced: 250" in result[0].text
        assert mock_api.list_chats.await_count == 2
        mock_api.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_messages_date_filters_expand_date_only_inputs(self):
        mock_api = AsyncMock()
        mock_api.search_messages.return_value = {"results": [], "total": 0, "query": "test"}

        with patch("telegram_wai_mcp.server.get_client", return_value=mock_api):
            result = await server.call_tool(
                "search_messages",
                {
                    "query": "test",
                    "date_from": "2026-01-29",
                    "date_to": "2026-01-29",
                },
            )

        assert result[0].text.startswith("No messages found")
        kwargs = mock_api.search_messages.await_args.kwargs
        assert kwargs["date_from"] == datetime(2026, 1, 29, 0, 0, tzinfo=UTC)
        assert kwargs["date_to"] == datetime(2026, 1, 29, 23, 59, 59, 999999, tzinfo=UTC)
        mock_api.close.assert_awaited_once()


class TestFormatHelpers:
    def test_format_search_results_with_results(self):
        result = {
            "results": [
                {
                    "text": "hello world",
                    "chat_title": "Test Chat",
                    "chat_username": "test_chat",
                    "sender_name": "John",
                    "sent_at": "2024-01-01T12:00:00Z",
                    "similarity": 0.95,
                    "is_outgoing": False,
                    "has_media": False,
                }
            ],
            "total": 1,
            "query": "hello",
        }
        content = server.format_search_results(result)
        assert len(content) >= 1
        assert "Found" in content[0].text
        assert "@test_chat" in content[0].text
        assert "https://t.me/test_chat" in content[0].text

    def test_format_search_results_private_supergroup_link_fallback(self):
        result = {
            "results": [
                {
                    "text": "hello world",
                    "chat_title": "Private Team",
                    "chat_type": "supergroup",
                    "chat_telegram_id": -1001234567890,
                    "telegram_message_id": 321,
                    "sender_name": "John",
                    "sent_at": "2024-01-01T12:00:00Z",
                    "similarity": 0.95,
                    "is_outgoing": False,
                    "has_media": False,
                }
            ],
            "total": 1,
            "query": "hello",
        }
        content = server.format_search_results(result)
        assert "Open: https://t.me/c/1234567890/321" in content[0].text

    def test_format_search_results_empty(self):
        result = {"results": [], "total": 0, "query": "nothing"}
        content = server.format_search_results(result)
        assert len(content) == 1

    def test_format_search_results_tolerates_missing_fields(self):
        result = {"results": [{"text": "hello"}]}
        content = server.format_search_results(result)
        assert len(content) >= 1

    def test_format_search_results_keeps_full_text(self):
        long_text = "A" * 320
        result = {
            "results": [
                {
                    "text": long_text,
                    "chat_title": "Test Chat",
                    "sender_name": "John",
                    "sent_at": "2024-01-01T12:00:00Z",
                    "similarity": 0.95,
                    "is_outgoing": False,
                    "has_media": False,
                }
            ],
            "total": 1,
            "query": "hello",
        }
        content = server.format_search_results(result)
        assert long_text in content[0].text


class TestFormatChatList:
    def test_shows_count_header(self):
        result = {
            "chats": [
                {
                    "title": "Chat A",
                    "id": "1",
                    "chat_type": "private",
                    "username": "chat_a",
                }
            ],
            "total": 50,
            "has_more": True,
            "next_cursor": "cursor_abc",
        }
        content = server.format_chat_list(result)
        assert "Showing 1 of 50" in content[0].text
        assert "@chat_a" in content[0].text
        assert "https://t.me/chat_a" in content[0].text

    def test_shows_private_supergroup_link_when_username_missing(self):
        result = {
            "chats": [
                {
                    "title": "Private Team",
                    "id": "1",
                    "chat_type": "supergroup",
                    "telegram_chat_id": -1001234567890,
                    "last_message_id": 654,
                }
            ],
            "total": 1,
            "has_more": False,
        }
        content = server.format_chat_list(result)
        assert "Open: https://t.me/c/1234567890/654" in content[0].text

    def test_pagination_footer_when_has_more(self):
        result = {
            "chats": [{"title": "Chat A", "id": "1", "chat_type": "private"}],
            "total": 100,
            "has_more": True,
            "next_cursor": "cursor_xyz",
        }
        content = server.format_chat_list(result)
        text = content[0].text
        assert 'cursor="cursor_xyz"' in text
        assert "More chats available" in text

    def test_no_pagination_footer_when_no_more(self):
        result = {
            "chats": [{"title": "Chat A", "id": "1", "chat_type": "private"}],
            "total": 1,
            "has_more": False,
        }
        content = server.format_chat_list(result)
        assert "More chats available" not in content[0].text

    def test_empty_chats(self):
        result = {"chats": [], "total": 0}
        content = server.format_chat_list(result)
        assert "No chats synced" in content[0].text


class TestFormatDataStatus:
    def _make_chats(self, n: int) -> list[dict]:
        return [
            {
                "title": f"Chat {i}",
                "id": f"id-{i}",
                "chat_type": "private" if i % 2 == 0 else "group",
                "total_messages_synced": i * 10,
                "last_sync_at": f"2026-03-0{min(i, 9)}T12:00:00+00:00",
            }
            for i in range(1, n + 1)
        ]

    def test_shows_summary_not_full_list(self):
        chats = self._make_chats(20)
        result = {"chats": chats, "total": 20}
        settings = {"listener_active": False, "realtime_sync_enabled": True}
        content = server.format_data_status(settings, result)
        text = content[0].text
        # Should have summary stats
        assert "Total chats: 20" in text
        assert "Total messages synced:" in text
        assert "Chat types:" in text
        assert "Data freshness:" in text
        # Should only show 10 chats in the preview, not all 20
        assert text.count("ID: id-") == 10

    def test_top_10_cap(self):
        chats = self._make_chats(15)
        result = {"chats": chats, "total": 15}
        settings = {"listener_active": False, "realtime_sync_enabled": False}
        content = server.format_data_status(settings, result)
        text = content[0].text
        assert "Top 10" in text

    def test_footer_guidance(self):
        chats = self._make_chats(5)
        result = {"chats": chats, "total": 5}
        settings = {"listener_active": False, "realtime_sync_enabled": False}
        content = server.format_data_status(settings, result)
        text = content[0].text
        assert "list_chats" in text
        assert "search_messages" in text

    def test_empty_chats(self):
        result = {"chats": [], "total": 0}
        settings = {"listener_active": False, "realtime_sync_enabled": False}
        content = server.format_data_status(settings, result)
        assert "No chats synced" in content[0].text


class TestFormatChatMessages:
    def test_keeps_full_text(self):
        long_text = "B" * 360
        result = {
            "messages": [
                {
                    "telegram_message_id": 123,
                    "text": long_text,
                    "sender_name": "Jane",
                    "sent_at": "2024-01-01T12:00:00Z",
                    "is_outgoing": False,
                }
            ],
            "has_more": False,
            "total_messages_synced": 1,
            "last_sync_at": "2024-01-01T12:00:00Z",
        }
        content = server.format_chat_messages(result)
        assert long_text in content[0].text
