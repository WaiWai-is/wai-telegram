import asyncio
from datetime import date, datetime
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from telegram_wai_mcp.client import TelegramAIClient

# Initialize MCP server
server = Server("telegram-wai-mcp")
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
            description=(
                "Semantic search across synced Telegram messages. "
                "Finds messages by meaning using vector embeddings, not just keywords. "
                "Only searches messages that have been synced — if a chat was recently added "
                "or has few synced messages, use sync_chat first to download more history. "
                "Returns up to 100 results ranked by relevance."
            ),
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
                        "description": "Maximum results to return (1-100, default: 20)",
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
            description=(
                "List synced Telegram chats with metadata including message counts and last sync time. "
                "Use this to discover available chats and their IDs before reading messages or searching. "
                "Each chat shows total_messages_synced — if this number seems low for an active chat, "
                "use sync_chat to download more history."
            ),
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
            description=(
                "Read messages from a specific chat with cursor-based pagination. "
                "Returns messages newest-first. To page through history, pass the next_cursor "
                "value from the previous response as the 'before' parameter. "
                "IMPORTANT: When you reach 'End of synced messages', it means you've seen all "
                "messages currently in the database — but there may be older messages in Telegram "
                "that haven't been synced yet. The response includes total_messages_synced count. "
                "To download more history, use sync_chat with message_limit=0 for a full sync."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "string",
                        "description": "The chat ID to read messages from",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of messages to return per page (1-200, default: 50)",
                        "default": 50,
                    },
                    "before": {
                        "type": "string",
                        "description": "Pagination cursor from previous response's next_cursor — pass this to get the next (older) page of messages",
                    },
                },
                "required": ["chat_id"],
            },
        ),
        Tool(
            name="get_daily_digest",
            description=(
                "Get an AI-generated daily digest summarizing Telegram activity for a specific date. "
                "Covers the top active chats with message counts and key discussion points. "
                "Defaults to yesterday if no date is specified."
            ),
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
            description=(
                "Get a summary of recent activity in a specific chat. "
                "Shows message count and the most recent messages over the specified period. "
                "For comprehensive history, use get_chat_messages with pagination instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "string",
                        "description": "The chat ID to summarize",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of days to include (1-180, default: 7)",
                        "default": 7,
                    },
                },
                "required": ["chat_id"],
            },
        ),
        Tool(
            name="sync_chat",
            description=(
                "Download messages from Telegram for a specific chat. "
                "Use this when: (1) a chat has no or few synced messages, "
                "(2) you reached 'End of synced messages' but need older history, "
                "(3) you need the very latest messages that arrived after the last sync. "
                "Set message_limit=0 to download the ENTIRE chat history (recommended for first sync). "
                "The sync runs in the background — use get_sync_status to check progress."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "string",
                        "description": "The chat ID to sync",
                    },
                    "message_limit": {
                        "type": "integer",
                        "description": "Maximum messages to download. 0 = unlimited (full history). Default: 0 (download all messages).",
                        "default": 0,
                    },
                },
                "required": ["chat_id"],
            },
        ),
        Tool(
            name="get_sync_status",
            description=(
                "Check the progress of a sync job started with sync_chat. "
                "Returns status (pending/in_progress/completed/failed), messages processed count, "
                "and progress percentage. Poll this every few seconds until status is 'completed'."
            ),
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
                args, "message_limit", default=0, minimum=0, maximum=10000
            )
            result = await api.sync_chat(
                chat_id=chat_id,
                message_limit=message_limit if message_limit > 0 else None,
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
    lines = [f'Found {total} messages for query: "{query}"\n']
    for r in result.get("results", []):
        sender = r.get("sender_name") or ("You" if r.get("is_outgoing") else "Unknown")
        text = _format_media_label(r)[:200]
        similarity = r.get("similarity", 0) * 100
        sent_at = _format_date(r.get("sent_at"))
        chat_title = r.get("chat_title") or "Unknown"
        lines.append(
            f"[{chat_title}] {sender}: {text}\n  - Sent: {sent_at} | Relevance: {similarity:.0f}%\n"
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
        last_sync = chat.get("last_sync_at")
        sync_info = f"Last synced: {_format_date(last_sync)}" if last_sync else "Never synced"
        lines.append(
            f"- {title} ({chat_type})\n  ID: {chat_id} | Messages synced: {synced} | {sync_info}\n"
        )
    return [TextContent(type="text", text="\n".join(lines))]


def format_chat_messages(result: dict) -> list[TextContent]:
    """Format paginated chat messages for display."""
    messages = result.get("messages", [])
    if not messages:
        return [TextContent(type="text", text="No messages found in this chat.")]

    total_synced = result.get("total_messages_synced")
    last_sync = result.get("last_sync_at")

    lines = [f"Messages ({len(messages)} returned):\n"]
    for msg in messages:
        sender = msg.get("sender_name") or ("You" if msg.get("is_outgoing") else "Unknown")
        text = _format_media_label(msg)[:200]
        sent_at = _format_date(msg.get("sent_at"))
        lines.append(f"[{sent_at}] {sender}: {text}\n")

    has_more = result.get("has_more", False)
    next_cursor = result.get("next_cursor")
    if has_more and next_cursor:
        lines.append(
            f'\n--- More messages available. Use before="{next_cursor}" to load the next page ---'
        )
    else:
        # End of synced messages — provide context
        sync_parts = []
        if total_synced is not None:
            sync_parts.append(f"{total_synced} messages synced in total")
        if last_sync:
            sync_parts.append(f"last synced: {_format_date(last_sync)}")
        sync_info = " (" + ", ".join(sync_parts) + ")" if sync_parts else ""
        lines.append(
            f"\n--- End of synced messages{sync_info}. "
            f"There may be older messages in Telegram not yet downloaded. "
            f"Use sync_chat with message_limit=0 to download full history. ---"
        )

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
    total_synced = chat.get("total_messages_synced", 0)
    last_sync = chat.get("last_sync_at")
    msg_count = result.get("message_count", 0)
    period = result.get("period_days", "unknown")

    lines = [
        f"Chat: {chat.get('title', 'Unknown')}\n",
        f"Period: Last {period} days | Messages in period: {msg_count} | Total synced: {total_synced}\n",
    ]
    if last_sync:
        lines.append(f"Last synced: {_format_date(last_sync)}\n")

    recent = result.get("messages", [])
    if recent:
        lines.append(f"\nRecent messages ({len(recent)} shown):\n")
        for msg in recent:
            sender = msg.get("sender_name") or ("You" if msg.get("is_outgoing") else "Unknown")
            text = _format_media_label(msg)[:150]
            sent_at = _format_date(msg.get("sent_at"))
            lines.append(f"[{sent_at}] {sender}: {text}\n")
    else:
        lines.append("\nNo messages found in this period.\n")

    if msg_count > len(recent):
        lines.append(
            f"\nShowing {len(recent)} of {msg_count} messages. "
            f"Use get_chat_messages for full paginated access."
        )

    return [TextContent(type="text", text="\n".join(lines))]


def format_sync_started(result: dict) -> list[TextContent]:
    """Format sync started response."""
    job_id = result.get("id") or result.get("job_id", "unknown")
    status = result.get("status", "unknown")
    lines = [
        "Sync started successfully.\n",
        f"Job ID: {job_id}\n",
        f"Status: {status}\n",
        f'\nUse get_sync_status with job_id="{job_id}" to check progress.',
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
        lines.append("\nSync is still running. Check again in a few seconds.")
    elif status == "completed":
        lines.append("\nSync completed. You can now read the messages with get_chat_messages.")

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
