"""Celery tasks for executing digital agents on schedule.

The run_due_agents task checks every minute for agents whose next_run_at
has passed, and dispatches execute_agent for each one.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from celery import shared_task

from app.core.async_runner import run_async

logger = logging.getLogger(__name__)

# Max tool-calling rounds per agent execution (prevents runaway costs)
MAX_TOOL_ROUNDS = 10

# Responses API function tool available to scheduled agents.
SEARCH_WEB_TOOL = {
    "type": "function",
    "name": "search_web",
    "description": "Search the internet for current information. Use this to find news, facts, prices, events, or any real-time data.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query",
            },
        },
        "required": ["query"],
    },
}


def _build_tools_for_agent(agent_tools: str) -> list[dict]:
    """Build Responses API tools based on the agent's configured tools."""
    from app.services.agent.digital_agents import _normalize_agent_tools

    tools = []
    tool_names = _normalize_agent_tools(agent_tools).split(",")
    if "search_web" in tool_names:
        tools.append(SEARCH_WEB_TOOL)
    from app.services.tool_registry import responses_tool_definitions

    tools.extend(responses_tool_definitions(set(tool_names)))
    return tools


async def _execute_tool_call(
    tool_name: str,
    tool_input: dict,
    user_id: UUID | None = None,
) -> str:
    """Execute an agent tool call and return the result string."""
    if tool_name == "search_web":
        from app.services.agent.web_search import search_web

        query = tool_input.get("query", "")
        return await search_web(query)

    from app.services.tool_registry import _DEFINITION_BY_NAME, execute_data_tool

    if tool_name in _DEFINITION_BY_NAME:
        if user_id is None:
            raise ValueError("user_id is required for Telegram data tools")
        from app.core.database import get_db_context

        async with get_db_context() as db:
            result = await execute_data_tool(db, user_id, tool_name, tool_input)
        return json.dumps(result, ensure_ascii=False, default=str)

    return f"Unknown tool: {tool_name}"


@shared_task
def run_due_agents():
    """Find and execute all agents whose next_run_at <= now."""
    return run_async(_run_due_agents())


async def _run_due_agents() -> dict:
    from app.core.database import get_db_context
    from app.models.digital_agent import DigitalAgent
    from app.models.user import User

    now = datetime.now(UTC)
    dispatched = 0

    async with get_db_context() as db:
        from sqlalchemy import select

        result = await db.execute(
            select(DigitalAgent)
            .join(User, User.id == DigitalAgent.user_id)
            .where(
                DigitalAgent.status == "active",
                DigitalAgent.next_run_at <= now,
                DigitalAgent.next_run_at.isnot(None),
                User.is_active.is_(True),
            )
        )
        agents = result.scalars().all()

        for agent in agents:
            execute_agent.delay(str(agent.id))
            dispatched += 1

    return {"checked_at": now.isoformat(), "dispatched": dispatched}


@shared_task(bind=True, max_retries=2)
def execute_agent(self, agent_id: str):
    """Execute a single digital agent run."""
    return run_async(_execute_agent(UUID(agent_id)))


async def _execute_agent(agent_id: UUID) -> dict:
    from app.core.database import get_db_context
    from app.models.digital_agent import DigitalAgent
    from app.models.user import User
    from app.services.agent.digital_agents import compute_next_run
    from app.services.bot_service import send_telegram_message
    from app.services.generation_service import create_generation_response

    async with get_db_context() as db:
        from sqlalchemy import select

        result = await db.execute(
            select(DigitalAgent)
            .join(User, User.id == DigitalAgent.user_id)
            .where(
                DigitalAgent.id == agent_id,
                User.is_active.is_(True),
            )
        )
        agent = result.scalar_one_or_none()
        if not agent or agent.status != "active":
            return {"status": "skipped"}

        try:
            # Build tools based on agent config
            tools = _build_tools_for_agent(agent.tools or "")

            input_items: list = [
                {
                    "role": "user",
                    "content": f"Execute your task now. Current time: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}.",
                }
            ]

            output = ""
            max_tool_turns = min(MAX_TOOL_ROUNDS, max(1, agent.max_tool_turns))
            async with asyncio.timeout(agent.max_runtime_seconds):
                for _round in range(max_tool_turns + 1):
                    response = await create_generation_response(
                        input_items,
                        max_output_tokens=agent.max_tokens_per_run,
                        instructions=agent.system_prompt,
                        tools=tools,
                    )
                    function_calls = [
                        item for item in response.output if item.type == "function_call"
                    ]
                    if not function_calls:
                        output = response.output_text.strip()
                        if not output:
                            raise RuntimeError("Scheduled agent returned no text")
                        break

                    input_items.extend(response.output)
                    for call in function_calls:
                        tool_input = json.loads(call.arguments)
                        if not isinstance(tool_input, dict):
                            raise ValueError(
                                f"Tool arguments must be an object: {call.name}"
                            )
                        try:
                            result = await _execute_tool_call(
                                call.name,
                                tool_input,
                                agent.user_id,
                            )
                        except Exception as exc:
                            logger.error("Agent tool %s failed: %s", call.name, exc)
                            result = f"Error: {exc}"
                        input_items.append(
                            {
                                "type": "function_call_output",
                                "call_id": call.call_id,
                                "output": result,
                            }
                        )
                else:
                    raise RuntimeError(
                        f"Scheduled agent exceeded {max_tool_turns} tool rounds"
                    )

            # Send result to user
            header = f"🤖 *{agent.name}*\n\n"
            await send_telegram_message(agent.telegram_chat_id, header + output)

            # Update state
            agent.last_run_at = datetime.now(UTC)
            agent.run_count += 1
            agent.error_count = 0
            agent.last_result = output[:2000]
            agent.last_error = None

            # Compute next run
            if agent.cron_expression:
                agent.next_run_at = compute_next_run(agent.cron_expression)

            await db.commit()
            logger.info(
                f"Agent executed: {agent.name} (id={agent.id}, "
                f"run_count={agent.run_count})"
            )
            return {
                "agent_id": str(agent_id),
                "status": "completed",
                "budget": {
                    "max_output_tokens": agent.max_tokens_per_run,
                    "max_runtime_seconds": agent.max_runtime_seconds,
                    "max_tool_turns": max_tool_turns,
                },
            }

        except Exception as e:
            agent.error_count += 1
            agent.last_error = str(e)[:500]

            # Auto-disable after 10 consecutive errors
            if agent.error_count >= 10:
                agent.status = "failed"
                logger.error(
                    f"Agent auto-disabled after 10 errors: {agent.name} (id={agent.id})"
                )

            await db.commit()
            logger.error(f"Agent execution failed: {agent.name} - {e}")
            return {"agent_id": str(agent_id), "status": "error", "error": str(e)}
