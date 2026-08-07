"""Digital Agents service — create and manage autonomous AI agents.

Users create agents from natural language descriptions.
The shared generation model parses the description into a structured config.
Agents run on Celery Beat and send results to Telegram.
"""

import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.digital_agent import DigitalAgent
from app.services.generation_service import generate_text
from app.services.tool_registry import TOOL_DEFINITIONS

logger = logging.getLogger(__name__)

_AGENT_TOOL_NAMES = (
    "search_web",
    *(definition.name for definition in TOOL_DEFINITIONS),
)

CREATION_PROMPT = """Analyze this user request and create a digital agent configuration.

User request: {description}

Extract:
1. name — short name for the agent (max 50 chars, in the user's language)
2. schedule — when to run. Parse natural language:
   - "every morning" / "каждое утро" → "0 9 * * *"
   - "every hour" / "каждый час" → "0 * * * *"
   - "every Monday" / "каждый понедельник" → "0 9 * * 1"
   - "twice a day" / "два раза в день" → "0 9,21 * * *"
   - If no schedule specified → "manual"
3. tools — which tools the agent needs (comma-separated), using only this list:
{tool_catalog}
4. system_prompt — optimized prompt for the agent's task. Be specific about output format.

Respond in JSON only, no explanation:
{{"name": "...", "cron": "...", "tools": "...", "system_prompt": "..."}}"""


def _render_creation_prompt(description: str) -> str:
    catalog = ["   - search_web — search current internet information"]
    catalog.extend(
        f"   - {definition.name} — {definition.description}"
        for definition in TOOL_DEFINITIONS
    )
    return CREATION_PROMPT.format(
        description=description,
        tool_catalog="\n".join(catalog),
    )


def _normalize_agent_tools(raw_tools: str) -> str:
    if not isinstance(raw_tools, str):
        raise ValueError("Scheduled-agent tools must be a comma-separated string")
    selected = {name.strip() for name in raw_tools.split(",") if name.strip()}
    unsupported = selected.difference(_AGENT_TOOL_NAMES)
    if unsupported:
        raise ValueError(
            "Unsupported scheduled-agent tool: " + ", ".join(sorted(unsupported))
        )
    return ",".join(name for name in _AGENT_TOOL_NAMES if name in selected)


async def create_agent_from_description(
    db: AsyncSession,
    user_id: UUID,
    telegram_chat_id: int,
    description: str,
) -> DigitalAgent:
    """Parse a natural language description into a structured agent."""

    raw = await generate_text(
        _render_creation_prompt(description),
        max_output_tokens=500,
    )
    # Strip markdown if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0] if "```" in raw else raw

    config = json.loads(raw)
    if not isinstance(config, dict):
        raise ValueError("Scheduled-agent configuration must be a JSON object")
    for field in ("name", "cron", "tools", "system_prompt"):
        if not isinstance(config.get(field), str) or not config[field].strip():
            raise ValueError(
                f"Scheduled-agent field {field} must be a non-empty string"
            )

    name = config["name"].strip()
    system_prompt = config["system_prompt"].strip()
    normalized_tools = _normalize_agent_tools(config["tools"])

    # Compute next run
    cron = config["cron"].strip()
    next_run = None
    schedule_type = "manual"
    if cron and cron != "manual":
        schedule_type = "cron"
        next_run = compute_next_run(cron)

    agent = DigitalAgent(
        user_id=user_id,
        telegram_chat_id=telegram_chat_id,
        name=name[:50],
        description=description,
        system_prompt=system_prompt,
        tools=normalized_tools,
        schedule_type=schedule_type,
        cron_expression=cron if cron != "manual" else None,
        status="active",
        next_run_at=next_run,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    logger.info(
        f"Agent created: {agent.name} (id={agent.id}, schedule={schedule_type}, "
        f"cron={cron}, tools={agent.tools})"
    )
    return agent


async def list_user_agents(db: AsyncSession, user_id: UUID) -> list[DigitalAgent]:
    """List active agents for a user."""
    result = await db.execute(
        select(DigitalAgent)
        .where(DigitalAgent.user_id == user_id, DigitalAgent.status != "deleted")
        .order_by(DigitalAgent.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_agent(db: AsyncSession, user_id: UUID, agent_id: UUID) -> bool:
    """Soft-delete an agent."""
    result = await db.execute(
        select(DigitalAgent).where(
            DigitalAgent.id == agent_id,
            DigitalAgent.user_id == user_id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return False
    agent.status = "deleted"
    await db.commit()
    logger.info(f"Agent deleted: {agent.name} (id={agent.id})")
    return True


async def trigger_agent(
    db: AsyncSession, user_id: UUID, agent_id: UUID
) -> DigitalAgent | None:
    """Get an agent for manual triggering."""
    result = await db.execute(
        select(DigitalAgent).where(
            DigitalAgent.id == agent_id,
            DigitalAgent.user_id == user_id,
            DigitalAgent.status == "active",
        )
    )
    return result.scalar_one_or_none()


def compute_next_run(
    cron_expression: str, from_time: datetime | None = None
) -> datetime:
    """Compute the next run time from a cron expression."""
    base = from_time or datetime.now(UTC)
    cron = croniter(cron_expression, base)
    return cron.get_next(datetime).replace(tzinfo=base.tzinfo)


def format_agents_list(agents: list[DigitalAgent]) -> str:
    """Format agent list for Telegram display."""
    if not agents:
        return (
            "🤖 No agents yet.\n\n"
            "Create one:\n"
            "`/agent create Check HackerNews for AI articles every morning`"
        )

    lines = [f"🤖 *Your Agents* ({len(agents)})\n"]
    for agent in agents:
        status_icon = (
            "✅"
            if agent.status == "active"
            else "⏸️"
            if agent.status == "paused"
            else "❌"
        )
        schedule = agent.cron_expression or "manual"
        runs = f"{agent.run_count} runs" if agent.run_count else "not run yet"
        lines.append(f"{status_icon} *{agent.name}*")
        lines.append(f"   ⏰ `{schedule}` | {runs}")
        lines.append(f"   ID: `{str(agent.id)[:8]}`\n")

    lines.append("_/agent run <id> — trigger now_")
    lines.append("_/agent delete <id> — remove_")
    return "\n".join(lines)
