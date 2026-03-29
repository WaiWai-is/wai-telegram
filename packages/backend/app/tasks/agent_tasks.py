"""Celery tasks for executing digital agents on schedule.

The run_due_agents task checks every minute for agents whose next_run_at
has passed, and dispatches execute_agent for each one.
"""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from celery import shared_task

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@shared_task
def run_due_agents():
    """Find and execute all agents whose next_run_at <= now."""
    return asyncio.run(_run_due_agents())


async def _run_due_agents() -> dict:
    from app.core.database import dispose_engine, get_db_context
    from app.models.digital_agent import DigitalAgent

    await dispose_engine()
    now = datetime.now(UTC)
    dispatched = 0

    async with get_db_context() as db:
        from sqlalchemy import select

        result = await db.execute(
            select(DigitalAgent).where(
                DigitalAgent.status == "active",
                DigitalAgent.next_run_at <= now,
                DigitalAgent.next_run_at.isnot(None),
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
    return asyncio.run(_execute_agent(UUID(agent_id)))


async def _execute_agent(agent_id: UUID) -> dict:
    import anthropic

    from app.core.database import dispose_engine, get_db_context
    from app.models.digital_agent import DigitalAgent
    from app.services.agent.digital_agents import compute_next_run
    from app.services.bot_service import send_telegram_message

    await dispose_engine()

    async with get_db_context() as db:
        from sqlalchemy import select

        result = await db.execute(
            select(DigitalAgent).where(DigitalAgent.id == agent_id)
        )
        agent = result.scalar_one_or_none()
        if not agent or agent.status != "active":
            return {"status": "skipped"}

        try:
            # Call Claude with the agent's system prompt
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=agent.max_tokens_per_run,
                system=agent.system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": f"Execute your task now. Current time: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}.",
                    }
                ],
            )
            output = response.content[0].text.strip()

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
            return {"agent_id": str(agent_id), "status": "completed"}

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
