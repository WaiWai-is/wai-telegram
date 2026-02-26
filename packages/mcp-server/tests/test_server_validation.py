import pytest
from telegram_wai_mcp import server


@pytest.mark.asyncio
async def test_call_tool_rejects_invalid_digest_date() -> None:
    content = await server.call_tool("get_daily_digest", {"date": "not-a-date"})
    assert len(content) == 1
    assert content[0].text.startswith("Error:")


@pytest.mark.asyncio
async def test_call_tool_requires_non_empty_query() -> None:
    content = await server.call_tool("search_messages", {"query": ""})
    assert len(content) == 1
    assert '"query" must be a non-empty string' in content[0].text


def test_format_search_results_tolerates_missing_fields() -> None:
    result = {"results": [{"text": "hello"}]}
    content = server.format_search_results(result)
    assert len(content) == 1
    assert "Found" in content[0].text
