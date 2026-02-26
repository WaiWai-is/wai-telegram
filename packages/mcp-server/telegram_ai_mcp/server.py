import asyncio
from datetime import date, datetime
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from telegram_ai_mcp.client import TelegramAIClient

# Initialize MCP server
server = Server("telegram-ai-mcp")
client: TelegramAIClient | None = None
MAX_LIMIT = 200
MAX_LOOKBACK_DAYS = 180

# Media type display labels
MEDIA_LABELS = {
    "photo": "Photo",
    "video": "Video",
    "audio": "Audio",
    "document": "Document",
    "voice": "Voice message",
    "video_note": "Video note",
}


def get_client() -> TelegramAIClient:
    global client
    if client is None:
        client = TelegramAIClient()
    return client


def _error(message: str) -> list[TextContent]:
    return [TextContent(type="text", text=f"Error: {message}")]


def _as_dict(arguments: dict[str, Any] | None) -> dict[str, Any]:
    return arguments or {}


def _require_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'"{key}" must be a non-empty string')
    return value.strip()


def _optional_int(
    arguments: dict[str, Any],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = arguments.get(key, default)
    if not isinstance(raw, int):
        raise ValueError(f'"{key}" must be an integer')
    return max(minimum, min(maximum, raw))


def _optional_iso_datetime(arguments: dict[str, Any], key: str) -> datetime | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f'"{key}" must be an ISO 8601 datetime string')
    try:
        return datetime.fromisoformat(value)
    except ValueError as e:
        raise ValueError(f'"{key}" must be an ISO 8601 datetime string') from e


def _optional_iso_date(arguments: dict[str, Any], key: str) -> date | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f'"{key}" must be a YYYY-MM-DD date string')
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise ValueError(f'"{key}" must be a YYYY-MM-DD date string') from e


def _format_date(value: Any) -> str:
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, datetime):
        return value.date().isoformat()
    return "unknown"


def _format_media_label(msg: dict) -> str:
    """Format a media label based on media_type, text, and transcribed_at."""
    media_type = msg.get("media_type")
    text = msg.get("text")
    transcribed_at = msg.get("transcribed_at")

    if media_type in ("voice", "video_note") and text and transcribed_at:
        label = "Voice transcript" if media_type == "voice" else "Video note transcript"
        return f"[{label}]: {text}"

    if media_type and text:
        # Has both media and text (e.g. photo with caption)
        return text

    if text:
        return text

    if media_type:
        label = MEDIA_LABELS.get(media_type, "Media")
        return f"[{label}]"

    return "[Media]"


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools."""
    return [
        Tool(
            name="search_messages",
            description="Semantic search across your Telegram messages. Finds messages by meaning, not just keywords.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query - describe what you're looking for",
                    },
                    "chat_id": {
                        "type": "string",
                        "description": "Optional: Limit search to a specific chat ID",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return (default: 20)",
                        "default": 20,
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Optional: Only return messages sent after this date (ISO 8601, e.g. 2025-01-15)",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Optional: Only return messages sent before this date (ISO 8601, e.g. 2025-02-15)",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="list_chats",
            description="List your synced Telegram chats (private, group, supergroup, or channel).",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_type": {
                        "type": "string",
                        "description": "Filter by chat type: private, group, supergroup, channel",
                        "enum": ["private", "group", "supergroup", "channel"],
                    },
                },
            },
        ),
        Tool(
            name="get_chat_messages",
            description="Read messages from a specific chat with pagination. Use the 'before' cursor to page through history.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "string",
                        "description": "The chat ID to read messages from",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of messages to return (default: 50, max: 200)",
                        "default": 50,
                    },
                    "before": {
                        "type": "string",
                        "description": "Pagination cursor - pass next_cursor from a previous response to get older messages",
                    },
                },
                "required": ["chat_id"],
            },
        ),
        Tool(
            name="get_daily_digest",
            description="Get an AI-generated daily digest summarizing your Telegram activity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format (defaults to yesterday)",
                    },
                },
            },
        ),
        Tool(
            name="get_chat_summary",
            description="Get a summary of activity in a specific chat over recent days.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "string",
                        "description": "The chat ID to summarize",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of days to include (default: 7)",
                        "default": 7,
                    },
                },
                "required": ["chat_id"],
            },
        ),
        Tool(
            name="sync_chat",
            description="Trigger a message sync from Telegram for a specific chat. Use when you need the latest messages or when a chat has incomplete data.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "string",
                        "description": "The chat ID to sync",
                    },
                    "message_limit": {
                        "type": "integer",
                        "description": "Maximum messages to sync (default: 500)",
                        "default": 500,
                    },
                },
                "required": ["chat_id"],
            },
        ),
        Tool(
            name="get_sync_status",
            description="Check the progress of a sync job started with sync_chat.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The job ID returned by sync_chat",
                    },
                },
                "required": ["job_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    api = get_client()
    args = _as_dict(arguments)

    try:
        if name == "search_messages":
            query = _require_str(args, "query")
            limit = _optional_int(args, "limit", default=20, minimum=1, maximum=100)
            date_from = _optional_iso_datetime(args, "date_from")
            date_to = _optional_iso_datetime(args, "date_to")
            chat_id = args.get("chat_id")
            if chat_id is not None and not isinstance(chat_id, str):
                raise ValueError('"chat_id" must be a string UUID')
            result = await api.search_messages(
                query=query,
                chat_ids=[chat_id] if chat_id else None,
                limit=limit,
                date_from=date_from,
                date_to=date_to,
            )
            return format_search_results(result)

        elif name == "list_chats":
            chat_type = args.get("chat_type")
            if chat_type is not None and not isinstance(chat_type, str):
                raise ValueError('"chat_type" must be a string')
            result = await api.list_chats(chat_type=chat_type)
            return format_chat_list(result)

        elif name == "get_chat_messages":
            chat_id = _require_str(args, "chat_id")
            limit = _optional_int(args, "limit", default=50, minimum=1, maximum=MAX_LIMIT)
            before = args.get("before")
            if before is not None and not isinstance(before, str):
                raise ValueError('"before" must be a string cursor')
            result = await api.get_messages(
                chat_id=chat_id,
                limit=limit,
                before=before,
            )
            return format_chat_messages(result)

        elif name == "get_daily_digest":
            digest_date = _optional_iso_date(args, "date")
            result = await api.get_daily_digest(digest_date)
            return format_digest(result)

        elif name == "get_chat_summary":
            chat_id = _require_str(args, "chat_id")
            days = _optional_int(
                args,
                "days",
                default=7,
                minimum=1,
                maximum=MAX_LOOKBACK_DAYS,
            )
            result = await api.get_chat_summary(
                chat_id=chat_id,
                days=days,
            )
            return format_chat_summary(result)

        elif name == "sync_chat":
            chat_id = _require_str(args, "chat_id")
            message_limit = _optional_int(
                args, "message_limit", default=500, minimum=1, maximum=10000
            )
            result = await api.sync_chat(
                chat_id=chat_id,
                message_limit=message_limit,
            )
            return format_sync_started(result)

        elif name == "get_sync_status":
            job_id = _require_str(args, "job_id")
            result = await api.get_sync_status(job_id)
            return format_sync_status(result)

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except ValueError as e:
        return _error(str(e))
    except Exception as e:
        return _error(str(e))


def format_search_results(result: dict) -> list[TextContent]:
    """Format search results for display."""
    if not result.get("results"):
        return [TextContent(type="text", text="No messages found matching your query.")]

    total = result.get("total", 0)
    query = result.get("query", "")
    lines = [f"Found {total} messages for query: \"{query}\"\n"]
    for r in result.get("results", []):
        sender = r.get("sender_name") or ("You" if r.get("is_outgoing") else "Unknown")
        text = _format_media_label(r)[:200]
        similarity = r.get("similarity", 0) * 100
        sent_at = _format_date(r.get("sent_at"))
        chat_title = r.get("chat_title") or "Unknown"
        lines.append(
            f"[{chat_title}] {sender}: {text}\n"
            f"  - Sent: {sent_at} | Relevance: {similarity:.0f}%\n"
        )
    return [TextContent(type="text", text="\n".join(lines))]


def format_chat_list(result: dict) -> list[TextContent]:
    """Format chat list for display."""
    if not result.get("chats"):
        return [TextContent(type="text", text="No chats synced yet.")]

    lines = [f"Your Telegram Chats ({result.get('total', 0)} total):\n"]
    for chat in result.get("chats", []):
        synced = chat.get("total_messages_synced", 0)
        title = chat.get("title", "Unknown")
        chat_type = chat.get("chat_type", "unknown")
        chat_id = chat.get("id", "unknown")
        lines.append(
            f"• {title} ({chat_type})\n"
            f"  ID: {chat_id} | Messages: {synced}\n"
        )
    return [TextContent(type="text", text="\n".join(lines))]


def format_chat_messages(result: dict) -> list[TextContent]:
    """Format paginated chat messages for display."""
    messages = result.get("messages", [])
    if not messages:
        return [TextContent(type="text", text="No messages found in this chat.")]

    lines = [f"Messages ({len(messages)} returned):\n"]
    for msg in messages:
        sender = msg.get("sender_name") or ("You" if msg.get("is_outgoing") else "Unknown")
        text = _format_media_label(msg)[:200]
        sent_at = _format_date(msg.get("sent_at"))
        lines.append(f"[{sent_at}] {sender}: {text}\n")

    has_more = result.get("has_more", False)
    next_cursor = result.get("next_cursor")
    if has_more and next_cursor:
        lines.append(f"\n--- More messages available. Use before=\"{next_cursor}\" to continue ---")
    elif not has_more:
        lines.append("\n--- End of messages ---")

    return [TextContent(type="text", text="\n".join(lines))]


def format_digest(result: dict) -> list[TextContent]:
    """Format digest for display."""
    lines = [
        f"Daily Digest for {result.get('digest_date', 'unknown')}\n",
        "=" * 40 + "\n",
        result.get("content", "No digest content available."),
        "\n" + "=" * 40,
        f"\nStats: {result.get('summary_stats', {})}",
    ]
    return [TextContent(type="text", text="\n".join(lines))]


def format_chat_summary(result: dict) -> list[TextContent]:
    """Format chat summary for display."""
    chat = result.get("chat", {})
    lines = [
        f"Chat Summary: {chat.get('title', 'Unknown')}\n",
        f"Period: Last {result.get('period_days', 'unknown')} days\n",
        f"Messages: {result.get('message_count', 0)}\n",
        "\nRecent messages:\n",
    ]
    for msg in result.get("messages", [])[:10]:
        sender = msg.get("sender_name", "Unknown")
        text = _format_media_label(msg)[:100]
        lines.append(f"• {sender}: {text}\n")
    return [TextContent(type="text", text="\n".join(lines))]


def format_sync_started(result: dict) -> list[TextContent]:
    """Format sync started response."""
    job_id = result.get("id") or result.get("job_id", "unknown")
    status = result.get("status", "unknown")
    lines = [
        f"Sync started successfully.\n",
        f"Job ID: {job_id}\n",
        f"Status: {status}\n",
        f"\nUse get_sync_status with job_id=\"{job_id}\" to check progress.",
    ]
    return [TextContent(type="text", text="\n".join(lines))]


def format_sync_status(result: dict) -> list[TextContent]:
    """Format sync status response."""
    job_id = result.get("job_id", "unknown")
    status = result.get("status", "unknown")
    messages_processed = result.get("messages_processed", 0)
    progress = result.get("progress_percent")
    error = result.get("error_message")

    lines = [
        f"Sync Job: {job_id}\n",
        f"Status: {status}\n",
        f"Messages processed: {messages_processed}\n",
    ]
    if progress is not None:
        lines.append(f"Progress: {progress}%\n")
    if error:
        lines.append(f"Error: {error}\n")
    if status == "in_progress":
        lines.append(f"\nSync is still running. Check again in a few seconds.")
    elif status == "completed":
        lines.append(f"\nSync completed. You can now read the messages with get_chat_messages.")

    return [TextContent(type="text", text="\n".join(lines))]


def main():
    """Run the MCP server."""
    asyncio.run(run_server())


async def run_server():
    """Run the server with stdio transport."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    main()
