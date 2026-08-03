"""Tests for scheduled digital agents and their Responses API tool loop."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.digital_agent import DigitalAgent
from app.services.agent.digital_agents import compute_next_run, format_agents_list
from app.tasks.agent_tasks import (
    MAX_TOOL_ROUNDS,
    _build_tools_for_agent,
    _execute_agent,
    _execute_tool_call,
)


def _agent(**overrides):
    values = {
        "id": uuid4(),
        "status": "active",
        "tools": "",
        "system_prompt": "You are a test agent.",
        "max_tokens_per_run": 1024,
        "name": "Test Agent",
        "telegram_chat_id": 123456,
        "cron_expression": None,
        "run_count": 0,
        "error_count": 0,
    }
    values.update(overrides)
    return MagicMock(**values)


def _response(text: str = "", calls: list | None = None):
    return SimpleNamespace(output=calls or [], output_text=text)


def _call(query: str = "crypto news"):
    return SimpleNamespace(
        type="function_call",
        name="search_web",
        arguments=json.dumps({"query": query}),
        call_id="call_1",
    )


def _db_context(agent):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = agent
    db.execute.return_value = result
    context = MagicMock()
    context.return_value.__aenter__ = AsyncMock(return_value=db)
    context.return_value.__aexit__ = AsyncMock(return_value=False)
    return db, context


@pytest.mark.parametrize(
    ("cron", "base", "expected"),
    [
        ("0 9 * * *", datetime(2026, 3, 29, 8, tzinfo=UTC), (29, 9)),
        ("0 * * * *", datetime(2026, 3, 29, 8, 30, tzinfo=UTC), (29, 9)),
        ("0 9 * * 1", datetime(2026, 3, 29, 10, tzinfo=UTC), (30, 9)),
    ],
)
def test_compute_next_run(cron, base, expected):
    value = compute_next_run(cron, base)
    assert (value.day, value.hour) == expected
    assert value > base


def test_format_agents_list():
    assert "/agent create" in format_agents_list([])
    agent = DigitalAgent(
        id=uuid4(),
        user_id=uuid4(),
        telegram_chat_id=123456,
        name="Test Agent",
        description="test",
        system_prompt="test prompt",
        tools="search_web",
        schedule_type="cron",
        cron_expression="0 9 * * *",
        status="active",
        run_count=5,
    )
    rendered = format_agents_list([agent])
    assert "Test Agent" in rendered
    assert "5 runs" in rendered
    assert "✅" in rendered


def test_build_tools_uses_responses_function_schema():
    assert _build_tools_for_agent("") == []
    tools = _build_tools_for_agent(" search_web , search_messages ")
    assert tools == [
        {
            "type": "function",
            "name": "search_web",
            "description": tools[0]["description"],
            "parameters": tools[0]["parameters"],
        }
    ]
    assert tools[0]["parameters"]["required"] == ["query"]


@pytest.mark.asyncio
async def test_execute_tool_call():
    with patch(
        "app.services.agent.web_search.search_web",
        new_callable=AsyncMock,
        return_value="BTC result",
    ) as search:
        assert (
            await _execute_tool_call("search_web", {"query": "bitcoin"}) == "BTC result"
        )
        search.assert_awaited_once_with("bitcoin")
    assert "Unknown tool" in await _execute_tool_call("missing", {})


@pytest.mark.asyncio
async def test_agent_without_tools_sends_single_luna_response():
    agent = _agent()
    db, db_context = _db_context(agent)
    generation = AsyncMock(return_value=_response("Here is the output."))
    with (
        patch("app.core.database.get_db_context", db_context),
        patch("app.services.generation_service.create_generation_response", generation),
        patch(
            "app.services.bot_service.send_telegram_message",
            new_callable=AsyncMock,
        ) as send,
    ):
        result = await _execute_agent(agent.id)

    assert result["status"] == "completed"
    assert "Here is the output." in send.await_args.args[1]
    assert generation.await_args.kwargs["instructions"] == agent.system_prompt
    assert generation.await_args.kwargs["tools"] == []
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_function_call_is_executed_and_replayed():
    agent = _agent(
        tools="search_web",
        name="Crypto Agent",
        max_tokens_per_run=2048,
        cron_expression="0 9 * * *",
    )
    _db, db_context = _db_context(agent)
    call = _call("crypto news today")
    generation = AsyncMock(
        side_effect=[_response(calls=[call]), _response("Bitcoin is up today.")]
    )
    with (
        patch("app.core.database.get_db_context", db_context),
        patch("app.services.generation_service.create_generation_response", generation),
        patch(
            "app.services.bot_service.send_telegram_message",
            new_callable=AsyncMock,
        ) as send,
        patch(
            "app.tasks.agent_tasks._execute_tool_call",
            new_callable=AsyncMock,
            return_value="current results",
        ) as execute,
        patch(
            "app.services.agent.digital_agents.compute_next_run",
            return_value=datetime(2026, 3, 30, 9, tzinfo=UTC),
        ),
    ):
        result = await _execute_agent(agent.id)

    assert result["status"] == "completed"
    execute.assert_awaited_once_with("search_web", {"query": "crypto news today"})
    assert generation.await_count == 2
    second_input = generation.await_args_list[1].args[0]
    assert second_input[-1] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "current results",
    }
    assert "Bitcoin is up today." in send.await_args.args[1]


@pytest.mark.asyncio
async def test_agent_tool_limit_is_reported_as_error_without_sending():
    agent = _agent(tools="search_web", name="Looper")
    _db, db_context = _db_context(agent)
    generation = AsyncMock(return_value=_response(calls=[_call("loop")]))
    with (
        patch("app.core.database.get_db_context", db_context),
        patch("app.services.generation_service.create_generation_response", generation),
        patch(
            "app.services.bot_service.send_telegram_message",
            new_callable=AsyncMock,
        ) as send,
        patch(
            "app.tasks.agent_tasks._execute_tool_call",
            new_callable=AsyncMock,
            return_value="result",
        ),
    ):
        result = await _execute_agent(agent.id)

    assert result["status"] == "error"
    assert "tool rounds" in result["error"]
    assert generation.await_count == MAX_TOOL_ROUNDS + 1
    send.assert_not_awaited()
