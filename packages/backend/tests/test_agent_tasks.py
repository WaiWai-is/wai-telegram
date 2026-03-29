"""Tests for digital agent tasks and service."""

from datetime import UTC, datetime
from uuid import uuid4

from app.models.digital_agent import DigitalAgent
from app.services.agent.digital_agents import (
    compute_next_run,
    format_agents_list,
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
