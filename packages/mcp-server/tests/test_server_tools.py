import pytest
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
        content = await server.call_tool("nonexistent_tool", {})
        assert len(content) == 1
        assert "Unknown tool" in content[0].text

    @pytest.mark.asyncio
    async def test_search_messages_requires_query(self):
        content = await server.call_tool("search_messages", {"query": ""})
        assert len(content) == 1
        assert "non-empty" in content[0].text.lower()


class TestFormatHelpers:
    def test_format_search_results_with_results(self):
        result = {
            "results": [
                {
                    "text": "hello world",
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
        assert len(content) >= 1
        assert "Found" in content[0].text

    def test_format_search_results_empty(self):
        result = {"results": [], "total": 0, "query": "nothing"}
        content = server.format_search_results(result)
        assert len(content) == 1

    def test_format_search_results_tolerates_missing_fields(self):
        result = {"results": [{"text": "hello"}]}
        content = server.format_search_results(result)
        assert len(content) >= 1
