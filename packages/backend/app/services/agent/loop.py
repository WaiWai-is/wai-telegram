"""Agent Loop — the core execution engine.

Inspired by OpenCode's server-first architecture and OpenClaw's lane queue pattern.
Each user gets a serial execution queue (no concurrent agent turns per user).

Flow:
1. Message arrives from Telegram
2. Intent Router classifies → right agent type
3. Model Router picks → right model for the task
4. Soul Prompt assembled with memory context
5. Agent executes with tool calling
6. Result sent back to Telegram
"""

import logging
from dataclasses import dataclass, field
from uuid import UUID

import anthropic

from app.core.config import get_settings
from app.services.agent.router import Intent, classify_intent, get_model_for_intent
from app.services.agent.soul import build_soul_prompt

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_TURNS = 10  # Max tool-calling turns per interaction


@dataclass
class AgentMessage:
    role: str  # "user" or "assistant"
    content: str


@dataclass
class AgentContext:
    user_id: UUID
    chat_id: int  # Telegram chat ID
    user_name: str | None = None
    user_language: str = "en"
    timezone: str = "UTC"
    connected_services: list[str] = field(default_factory=list)
    identity_memories: list[str] = field(default_factory=list)
    working_context: list[str] = field(default_factory=list)
    recalled_memories: list[str] = field(default_factory=list)
    conversation_history: list[AgentMessage] = field(default_factory=list)
    has_voice: bool = False
    voice_transcript: str | None = None


@dataclass
class AgentResult:
    response: str
    intent: Intent
    model_used: str
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0


# Tool definitions for Claude's tool_use
TOOLS = [
    {
        "name": "search_messages",
        "description": "Search user's Telegram message history by semantic meaning. Returns relevant messages with sender, chat, and date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query",
                },
                "chat_name": {
                    "type": "string",
                    "description": "Optional: filter by chat name",
                },
                "date_from": {
                    "type": "string",
                    "description": "Optional: start date (YYYY-MM-DD)",
                },
                "date_to": {
                    "type": "string",
                    "description": "Optional: end date (YYYY-MM-DD)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_digest",
        "description": "Get AI-generated summary of user's Telegram activity for a specific date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format. Defaults to yesterday.",
                },
            },
        },
    },
    {
        "name": "track_commitment",
        "description": "Track a promise or commitment detected in conversation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "who": {
                    "type": "string",
                    "description": "Who made the promise (person name)",
                },
                "what": {
                    "type": "string",
                    "description": "What was promised",
                },
                "deadline": {
                    "type": "string",
                    "description": "When it should be done (YYYY-MM-DD or description)",
                },
                "direction": {
                    "type": "string",
                    "enum": ["i_promised", "they_promised"],
                    "description": "Whether user promised or someone else promised",
                },
            },
            "required": ["who", "what", "direction"],
        },
    },
    {
        "name": "extract_entities",
        "description": "Extract people, topics, decisions, dates, and amounts from text. Use when the user shares meeting notes, voice transcripts, or complex messages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to extract entities from",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "list_commitments",
        "description": "List open commitments/promises. Shows what the user promised others and what others promised the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["all", "i_promised", "they_promised"],
                    "description": "Filter by direction. Default: all",
                },
            },
        },
    },
    {
        "name": "search_web",
        "description": "Search the internet for current information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
            },
            "required": ["query"],
        },
    },
]


async def execute_tool(tool_name: str, tool_input: dict, context: AgentContext) -> str:
    """Execute a tool call and return the result as a string.

    This is the central dispatch for all agent tools.
    Each tool is sandboxed and validates that the user owns the resource.
    """
    logger.info(f"Executing tool: {tool_name} for user {context.user_id}")

    if tool_name == "search_messages":
        return await _tool_search_messages(tool_input, context)
    elif tool_name == "get_digest":
        return await _tool_get_digest(tool_input, context)
    elif tool_name == "track_commitment":
        return await _tool_track_commitment(tool_input, context)
    elif tool_name == "extract_entities":
        return _tool_extract_entities(tool_input)
    elif tool_name == "list_commitments":
        return _tool_list_commitments(tool_input, context)
    elif tool_name == "search_web":
        return f"[Web search for: {tool_input.get('query', '')}] (not yet implemented)"
    else:
        return f"Unknown tool: {tool_name}"


async def _tool_search_messages(tool_input: dict, context: AgentContext) -> str:
    """Search user's message history via the existing search service."""
    from app.core.database import async_session_factory
    from app.schemas.search import SearchRequest
    from app.services.search_service import semantic_search

    query = tool_input.get("query", "")
    request = SearchRequest(
        query=query,
        limit=10,
    )

    async with async_session_factory() as db:
        results = await semantic_search(db, context.user_id, request)

    if not results.results:
        return f"No messages found matching: {query}"

    lines = []
    for r in results.results:
        sender = r.sender_name or "Unknown"
        chat = r.chat_title or "Unknown chat"
        date = r.sent_at.strftime("%Y-%m-%d %H:%M") if r.sent_at else ""
        text = (r.text or "")[:300]
        lines.append(f"[{chat}] {sender} ({date}): {text}")

    return "\n\n".join(lines)


async def _tool_get_digest(tool_input: dict, context: AgentContext) -> str:
    """Get digest for a specific date."""
    from datetime import date

    from app.core.database import async_session_factory
    from app.services.digest_service import generate_digest

    date_str = tool_input.get("date")
    if date_str:
        try:
            digest_date = date.fromisoformat(date_str)
        except ValueError:
            digest_date = None
    else:
        digest_date = None

    async with async_session_factory() as db:
        digest = await generate_digest(db, context.user_id, digest_date)
        return digest.content or "No digest available for this date."


async def _tool_track_commitment(tool_input: dict, context: AgentContext) -> str:
    """Track a commitment using the real commitment store."""
    from app.services.agent.commitments import (
        Commitment,
        CommitmentDirection,
        save_commitment,
    )

    who = tool_input.get("who", "Unknown")
    what = tool_input.get("what", "")
    deadline = tool_input.get("deadline")
    direction_str = tool_input.get("direction", "they_promised")

    direction = (
        CommitmentDirection.I_PROMISED
        if direction_str == "i_promised"
        else CommitmentDirection.THEY_PROMISED
    )

    commitment = Commitment(
        who=who,
        what=what,
        direction=direction,
        deadline=deadline,
    )
    save_commitment(commitment, context.user_id)

    if direction == CommitmentDirection.I_PROMISED:
        deadline_text = f" by {deadline}" if deadline else ""
        return f"✅ Tracked: You promised {who} to {what}{deadline_text}"
    else:
        deadline_text = f" by {deadline}" if deadline else ""
        return f"✅ Tracked: {who} promised to {what}{deadline_text}"


def _tool_extract_entities(tool_input: dict) -> str:
    """Extract entities from text using fast pattern matching."""
    from app.services.agent.entities import (
        extract_entities_fast,
        format_entities_for_display,
    )

    text = tool_input.get("text", "")
    if not text:
        return "No text provided for entity extraction."

    entities = extract_entities_fast(text)
    return format_entities_for_display(entities)


def _tool_list_commitments(tool_input: dict, context: AgentContext) -> str:
    """List user's open commitments."""
    from app.services.agent.commitments import (
        CommitmentDirection,
        format_commitments_for_display,
        get_user_commitments,
    )

    direction_str = tool_input.get("direction", "all")

    if direction_str == "i_promised":
        direction = CommitmentDirection.I_PROMISED
    elif direction_str == "they_promised":
        direction = CommitmentDirection.THEY_PROMISED
    else:
        direction = None

    commitments = get_user_commitments(context.user_id, direction=direction)
    return format_commitments_for_display(commitments)


async def run_agent(context: AgentContext, message: str) -> AgentResult:
    """Run the agent loop: classify → route → execute → respond.

    This is the main entry point for all user interactions.
    """
    from app.services.agent.metrics import increment

    # 1. Classify intent
    increment("agent_requests_total")
    intent = await classify_intent(message, has_voice=context.has_voice)
    model = get_model_for_intent(intent)
    increment(f"agent_intent_{intent.value}")

    logger.info(f"Agent: intent={intent.value}, model={model}, user={context.user_id}")

    # 2. Build soul prompt
    system_prompt = build_soul_prompt(
        user_name=context.user_name,
        user_language=context.user_language,
        timezone=context.timezone,
        connected_services=context.connected_services,
        identity_memories=context.identity_memories,
        working_context=context.working_context,
        recalled_memories=context.recalled_memories,
    )

    # 3. Build message history
    messages = []
    for msg in context.conversation_history[-20:]:  # Last 20 messages
        messages.append({"role": msg.role, "content": msg.content})

    # Add the current message
    user_content = message
    if context.voice_transcript:
        user_content = (
            f"[Voice message transcript]: {context.voice_transcript}\n\nUser's text: {message}"
            if message
            else f"[Voice message transcript]: {context.voice_transcript}"
        )

    messages.append({"role": "user", "content": user_content})

    # 4. Agent loop with tool calling
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    total_input_tokens = 0
    total_output_tokens = 0
    tool_call_count = 0

    for turn in range(MAX_TURNS):
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=TOOLS,
        )

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        # Check if the agent wants to use a tool
        if response.stop_reason == "tool_use":
            # Find tool use blocks
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for block in assistant_content:
                if block.type == "tool_use":
                    tool_call_count += 1
                    result = await execute_tool(block.name, block.input, context)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )

            messages.append({"role": "user", "content": tool_results})
            continue

        # Agent finished — extract text response
        text_parts = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)

        final_response = (
            "\n".join(text_parts) if text_parts else "I processed your request."
        )

        increment("agent_tokens_input", total_input_tokens)
        increment("agent_tokens_output", total_output_tokens)
        increment("agent_tool_calls", tool_call_count)
        return AgentResult(
            response=final_response,
            intent=intent,
            model_used=model,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            tool_calls=tool_call_count,
        )

    # Max turns exceeded
    return AgentResult(
        response="I've been working on this but reached my turn limit. Here's what I found so far.",
        intent=intent,
        model_used=model,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        tool_calls=tool_call_count,
    )
