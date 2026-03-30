"""Tests for digital agent tasks and service."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.digital_agent import DigitalAgent
from app.services.agent.digital_agents import (
    compute_next_run,
    format_agents_list,
)
from app.tasks.agent_tasks import (
    _build_tools_for_agent,
    _execute_tool_call,
)


class TestComputeNextRun:
    def test_daily_cron(self):
        base = datetime(2026, 3, 29, 8, 0, 0, tzinfo=UTC)
        next_run = compute_next_run("0 9 * * *", base)
        assert next_run.hour == 9
        assert next_run.day == 29

    def test_hourly_cron(self):
        base = datetime(2026, 3, 29, 8, 30, 0, tzinfo=UTC)
        next_run = compute_next_run("0 * * * *", base)
        assert next_run.hour == 9
        assert next_run.minute == 0

    def test_weekly_cron(self):
        base = datetime(2026, 3, 29, 10, 0, 0, tzinfo=UTC)  # Sunday
        next_run = compute_next_run("0 9 * * 1", base)  # Monday
        assert next_run.day == 30  # Next Monday
        assert next_run.hour == 9

    def test_returns_future_datetime(self):
        now = datetime.now(UTC)
        next_run = compute_next_run("0 * * * *", now)
        assert next_run > now


class TestFormatAgentsList:
    def test_empty_list(self):
        result = format_agents_list([])
        assert "No agents" in result
        assert "/agent create" in result

    def test_single_active_agent(self):
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
        result = format_agents_list([agent])
        assert "Test Agent" in result
        assert "0 9 * * *" in result
        assert "5 runs" in result
        assert "✅" in result

    def test_paused_agent(self):
        agent = DigitalAgent(
            id=uuid4(),
            user_id=uuid4(),
            telegram_chat_id=123456,
            name="Paused Agent",
            description="test",
            system_prompt="test prompt",
            schedule_type="manual",
            status="paused",
            run_count=0,
        )
        result = format_agents_list([agent])
        assert "⏸️" in result
        assert "not run yet" in result

    def test_multiple_agents(self):
        agents = [
            DigitalAgent(
                id=uuid4(),
                user_id=uuid4(),
                telegram_chat_id=123456,
                name=f"Agent {i}",
                description="test",
                system_prompt="test",
                schedule_type="cron",
                status="active",
                run_count=i,
            )
            for i in range(3)
        ]
        result = format_agents_list(agents)
        assert "3" in result
        assert "Agent 0" in result
        assert "Agent 2" in result


class TestDigitalAgentModel:
    def test_creation(self):
        agent = DigitalAgent(
            id=uuid4(),
            user_id=uuid4(),
            telegram_chat_id=123,
            name="Test",
            description="desc",
            system_prompt="prompt",
            schedule_type="manual",
            status="active",
            tools="search_web",
            run_count=0,
            error_count=0,
            max_tokens_per_run=4096,
        )
        assert agent.status == "active"
        assert agent.run_count == 0
        assert agent.error_count == 0
        assert agent.max_tokens_per_run == 4096
        assert agent.tools == "search_web"

    def test_cron_agent(self):
        agent = DigitalAgent(
            id=uuid4(),
            user_id=uuid4(),
            telegram_chat_id=123,
            name="Cron Agent",
            description="desc",
            system_prompt="prompt",
            schedule_type="cron",
            cron_expression="0 9 * * *",
            tools="search_web,search_messages",
        )
        assert agent.schedule_type == "cron"
        assert agent.cron_expression == "0 9 * * *"
        assert "search_web" in agent.tools


class TestBuildToolsForAgent:
    def test_empty_tools(self):
        assert _build_tools_for_agent("") == []

    def test_search_web_included(self):
        tools = _build_tools_for_agent("search_web")
        assert len(tools) == 1
        assert tools[0]["name"] == "search_web"
        assert "input_schema" in tools[0]

    def test_multiple_tools_only_search_web_mapped(self):
        tools = _build_tools_for_agent("search_web,search_messages")
        # Only search_web has a tool definition in agent_tasks
        assert len(tools) == 1
        assert tools[0]["name"] == "search_web"

    def test_no_matching_tools(self):
        tools = _build_tools_for_agent("search_messages")
        assert tools == []

    def test_whitespace_handling(self):
        tools = _build_tools_for_agent(" search_web , other_tool ")
        assert len(tools) == 1
        assert tools[0]["name"] == "search_web"


class TestExecuteToolCall:
    @pytest.mark.asyncio
    async def test_search_web_tool(self):
        with patch(
            "app.services.agent.web_search.search_web",
            new_callable=AsyncMock,
            return_value="Search results for BTC",
        ) as mock_search:
            result = await _execute_tool_call("search_web", {"query": "bitcoin price"})
        assert result == "Search results for BTC"
        mock_search.assert_called_once_with("bitcoin price")

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        result = await _execute_tool_call("unknown_tool", {"data": "test"})
        assert "Unknown tool" in result


class TestExecuteAgentToolLoop:
    """Test the _execute_agent function handles tool calls correctly."""

    @pytest.mark.asyncio
    async def test_agent_no_tools_single_response(self):
        """Agent without tools gets a simple Claude response."""
        from app.tasks.agent_tasks import _execute_agent

        agent_id = uuid4()
        mock_agent = MagicMock()
        mock_agent.id = agent_id
        mock_agent.status = "active"
        mock_agent.tools = ""
        mock_agent.system_prompt = "You are a test agent."
        mock_agent.max_tokens_per_run = 1024
        mock_agent.name = "Test Agent"
        mock_agent.telegram_chat_id = 123456
        mock_agent.cron_expression = None
        mock_agent.run_count = 0
        mock_agent.error_count = 0

        # Mock Claude response (no tool use)
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Here is the output."
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [mock_text_block]

        mock_client = AsyncMock()
        mock_client.messages.create.return_value = mock_response

        # Mock DB
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_agent
        mock_db.execute.return_value = mock_result

        with (
            patch("app.core.database.dispose_engine", new_callable=AsyncMock),
            patch(
                "app.core.database.get_db_context",
            ) as mock_db_ctx,
            patch("anthropic.AsyncAnthropic", return_value=mock_client),
            patch(
                "app.services.bot_service.send_telegram_message",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _execute_agent(agent_id)

        assert result["status"] == "completed"
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "Here is the output." in sent_text
        # No tools kwarg should be passed for empty tools
        create_kwargs = mock_client.messages.create.call_args[1]
        assert "tools" not in create_kwargs

    @pytest.mark.asyncio
    async def test_agent_with_search_web_tool_loop(self):
        """Agent with search_web performs tool call then gets final response."""
        from app.tasks.agent_tasks import _execute_agent

        agent_id = uuid4()
        mock_agent = MagicMock()
        mock_agent.id = agent_id
        mock_agent.status = "active"
        mock_agent.tools = "search_web"
        mock_agent.system_prompt = "Search for crypto news."
        mock_agent.max_tokens_per_run = 2048
        mock_agent.name = "Crypto Agent"
        mock_agent.telegram_chat_id = 789
        mock_agent.cron_expression = "0 9 * * *"
        mock_agent.run_count = 3
        mock_agent.error_count = 0

        # First response: tool_use
        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.name = "search_web"
        mock_tool_block.input = {"query": "crypto news today"}
        mock_tool_block.id = "tool_123"

        mock_response_1 = MagicMock()
        mock_response_1.stop_reason = "tool_use"
        mock_response_1.content = [mock_tool_block]

        # Second response: final text
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Bitcoin is up 5% today."
        mock_response_2 = MagicMock()
        mock_response_2.stop_reason = "end_turn"
        mock_response_2.content = [mock_text_block]

        mock_client = AsyncMock()
        mock_client.messages.create.side_effect = [mock_response_1, mock_response_2]

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_agent
        mock_db.execute.return_value = mock_result

        with (
            patch("app.core.database.dispose_engine", new_callable=AsyncMock),
            patch("app.core.database.get_db_context") as mock_db_ctx,
            patch("anthropic.AsyncAnthropic", return_value=mock_client),
            patch(
                "app.services.bot_service.send_telegram_message",
                new_callable=AsyncMock,
            ) as mock_send,
            patch(
                "app.tasks.agent_tasks._execute_tool_call",
                new_callable=AsyncMock,
                return_value="DuckDuckGo results: BTC $70k",
            ) as mock_tool,
            patch(
                "app.services.agent.digital_agents.compute_next_run",
                return_value=datetime(2026, 3, 30, 9, 0, 0, tzinfo=UTC),
            ),
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _execute_agent(agent_id)

        assert result["status"] == "completed"
        # Tool was called
        mock_tool.assert_called_once_with("search_web", {"query": "crypto news today"})
        # Claude was called twice (initial + after tool result)
        assert mock_client.messages.create.call_count == 2
        # Tools included in kwargs
        first_call_kwargs = mock_client.messages.create.call_args_list[0][1]
        assert "tools" in first_call_kwargs
        assert first_call_kwargs["tools"][0]["name"] == "search_web"
        # Final output sent to user
        sent_text = mock_send.call_args[0][1]
        assert "Bitcoin is up 5% today." in sent_text

    @pytest.mark.asyncio
    async def test_agent_tool_loop_max_rounds(self):
        """Agent stops after MAX_TOOL_ROUNDS even if Claude keeps requesting tools."""
        from app.tasks.agent_tasks import MAX_TOOL_ROUNDS, _execute_agent

        agent_id = uuid4()
        mock_agent = MagicMock()
        mock_agent.id = agent_id
        mock_agent.status = "active"
        mock_agent.tools = "search_web"
        mock_agent.system_prompt = "Search agent."
        mock_agent.max_tokens_per_run = 2048
        mock_agent.name = "Looper"
        mock_agent.telegram_chat_id = 111
        mock_agent.cron_expression = None
        mock_agent.run_count = 0
        mock_agent.error_count = 0

        # Every response is a tool_use — Claude never finishes
        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.name = "search_web"
        mock_tool_block.input = {"query": "infinite loop"}
        mock_tool_block.id = "tool_loop"

        mock_response_tool = MagicMock()
        mock_response_tool.stop_reason = "tool_use"
        mock_response_tool.content = [mock_tool_block]

        mock_client = AsyncMock()
        mock_client.messages.create.return_value = mock_response_tool

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_agent
        mock_db.execute.return_value = mock_result

        with (
            patch("app.core.database.dispose_engine", new_callable=AsyncMock),
            patch("app.core.database.get_db_context") as mock_db_ctx,
            patch("anthropic.AsyncAnthropic", return_value=mock_client),
            patch(
                "app.services.bot_service.send_telegram_message",
                new_callable=AsyncMock,
            ),
            patch(
                "app.tasks.agent_tasks._execute_tool_call",
                new_callable=AsyncMock,
                return_value="search results",
            ),
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _execute_agent(agent_id)

        assert result["status"] == "completed"
        # Should have called Claude exactly MAX_TOOL_ROUNDS + 1 times
        assert mock_client.messages.create.call_count == MAX_TOOL_ROUNDS + 1
