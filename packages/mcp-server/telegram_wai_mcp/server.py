import asyncio
import os
from datetime import date, datetime
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from starlette.requests import Request

from telegram_wai_mcp.client import TelegramAIClient

# Initialize MCP server
server = Server("telegram-wai-mcp")
MAX_LIMIT = 500
MAX_LOOKBACK_DAYS = 180
_session_api_keys: dict[str, str] = {}

# Media type display labels
MEDIA_LABELS = {
    "photo": "Photo",
    "video": "Video",
    "audio": "Audio",
    "document": "Document",
    "voice": "Voice message",
    "video_note": "Video note",
}


def remember_session_api_key(session_id: str, api_key: str) -> None:
    if session_id and api_key:
        _session_api_keys[session_id] = api_key


def forget_session_api_key(session_id: str) -> None:
    _session_api_keys.pop(session_id, None)


def get_session_api_key(session_id: str) -> str | None:
    return _session_api_keys.get(session_id)


def _current_request() -> Request | None:
    try:
        request = server.request_context.request
    except LookupError:
        return None
    return request if isinstance(request, Request) else None


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def _resolve_api_key(request: Request | None) -> str | None:
    if request is not None:
        scope_api_key = request.scope.get("telegram_ai_api_key")
        if isinstance(scope_api_key, str) and scope_api_key:
            return scope_api_key

        bearer = _extract_bearer_token(request.headers.get("authorization"))
        if bearer:
            return bearer

        query_key = request.query_params.get("key", "").strip()
        if query_key:
            return query_key

        session_id = request.headers.get("mcp-session-id", "").strip()
        if session_id:
            return get_session_api_key(session_id)

    env_api_key = os.environ.get("TELEGRAM_AI_KEY", "").strip()
    return env_api_key or None


def get_client() -> TelegramAIClient:
    request = _current_request()
    api_key = _resolve_api_key(request)
    if request is not None and not api_key:
        raise RuntimeError(
            "Missing API key. Use Authorization: Bearer <key> or ?key=... when initializing the MCP session."
        )
    base_url = os.environ.get("TELEGRAM_AI_URL", "http://localhost:8000")
    return TelegramAIClient(base_url=base_url, api_key=api_key)


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
            name="get_data_status",
            description=(
                "Check the status of your Telegram data. Returns a compact summary: total chats/messages, "
                "chat type breakdown, data freshness distribution, and top 10 most recently active chats. "
                "**Call this first** to understand what data is available. "
                "Use list_chats to browse all chats, or search_messages to find specific content."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="search_messages",
            description=(
                "Semantic search across all synced messages using vector embeddings. "
                "Finds messages by meaning, not just keywords. Only searches already-synced data — "
                "if results seem incomplete, sync the relevant chat first."
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
                "List synced Telegram chats with message counts, sync status, and freshness. "
                "Returns paginated results — use the cursor from the response to load more pages. "
                "Use to discover chat IDs. If you're looking for a specific chat, prefer "
                "search_messages which searches across all chats at once."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_type": {
                        "type": "string",
                        "description": "Filter by chat type: private, group, supergroup, channel",
                        "enum": ["private", "group", "supergroup", "channel"],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of chats per page (1-200, default: 50)",
                        "default": 50,
                    },
                    "cursor": {
                        "type": "string",
                        "description": "Pagination cursor from previous response — pass to load the next page",
                    },
                },
            },
        ),
        Tool(
            name="get_chat_messages",
            description=(
                "Read messages from a chat, newest-first, with cursor pagination (up to 500 per page). "
                "Pass 'before' cursor from previous response to page backwards through history. "
                "When you reach 'End of synced messages', use sync_chat with message_limit=0 to "
                "download older history from Telegram."
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
                        "description": "Number of messages to return per page (1-500, default: 50)",
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
            name="sync_chat",
            description=(
                "Download messages from Telegram into the database. Use message_limit=0 for full history "
                "(recommended). Returns a job_id — poll get_sync_status every 10-15 seconds until completed. "
                "The progress will show messages fetched out of total (e.g., '362 of 1,500 messages'). "
                "After completion, use get_chat_messages to read the synced messages. "
                "Typical speed: ~200 messages/second for text, slower for chats with voice messages (transcription)."
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
                "Check sync job progress. Poll every 10-15 seconds until status is 'completed'. "
                "Returns status, messages fetched (seen) out of total from Telegram, "
                "messages saved to database, and progress percentage. "
                "The total becomes available after the first batch is fetched from Telegram."
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
        Tool(
            name="send_message",
            description=(
                "Send a text message to a Telegram chat as the connected user account. "
                "Requires a chat_id — get it from list_chats or search_messages results."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "string",
                        "description": "The chat ID to send the message to",
                    },
                    "text": {
                        "type": "string",
                        "description": "The message text to send",
                    },
                },
                "required": ["chat_id", "text"],
            },
        ),
        Tool(
            name="send_file",
            description=(
                "Download a file from a URL and send it to a Telegram chat as the connected user account. "
                "Supports any file type (PDF, images, documents, etc.). "
                "The file is downloaded server-side and sent via Telegram."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "string",
                        "description": "The chat ID to send the file to",
                    },
                    "file_url": {
                        "type": "string",
                        "description": "URL of the file to download and send",
                    },
                    "caption": {
                        "type": "string",
                        "description": "Optional caption text for the file",
                    },
                    "file_name": {
                        "type": "string",
                        "description": "Optional file name override (auto-detected from URL if omitted)",
                    },
                },
                "required": ["chat_id", "file_url"],
            },
        ),
        Tool(
            name="reply_to_message",
            description=(
                "Reply to a specific message in a Telegram chat. "
                "Requires telegram_message_id — the numeric Telegram message ID shown in "
                "search_messages and get_chat_messages results as 'msg#'. "
                "The reply appears as a quoted reply in the chat."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "string",
                        "description": "The chat ID containing the message to reply to",
                    },
                    "telegram_message_id": {
                        "type": "integer",
                        "description": "The Telegram message ID to reply to (from search/chat message results)",
                    },
                    "text": {
                        "type": "string",
                        "description": "The reply text",
                    },
                },
                "required": ["chat_id", "telegram_message_id", "text"],
            },
        ),
        Tool(
            name="search_today_requests",
            description=(
                "Search today's messages for specific requests or topics. "
                "Automatically filters to today only. "
                "Useful for finding who asked for something today (e.g., 'who asked for the presentation')."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for in today's messages",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (1-100, default: 20)",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    args = _as_dict(arguments)
    api: TelegramAIClient | None = None

    try:
        api = get_client()
        if name == "get_data_status":
            settings = await api.get_settings()
            chats_result = await api.list_chats(limit=100)
            return format_data_status(settings, chats_result)

        elif name == "search_messages":
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
            limit = _optional_int(args, "limit", default=50, minimum=1, maximum=200)
            cursor = args.get("cursor")
            if cursor is not None and not isinstance(cursor, str):
                raise ValueError('"cursor" must be a string')
            result = await api.list_chats(chat_type=chat_type, limit=limit, cursor=cursor)
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

        elif name == "send_message":
            chat_id = _require_str(args, "chat_id")
            text = _require_str(args, "text")
            result = await api.send_message(chat_id=chat_id, text=text)
            return format_send_result(result, "Message sent")

        elif name == "send_file":
            chat_id = _require_str(args, "chat_id")
            file_url = _require_str(args, "file_url")
            caption = args.get("caption")
            file_name = args.get("file_name")
            result = await api.send_file(
                chat_id=chat_id,
                file_url=file_url,
                caption=caption,
                file_name=file_name,
            )
            return format_send_result(result, "File sent")

        elif name == "reply_to_message":
            chat_id = _require_str(args, "chat_id")
            telegram_message_id = args.get("telegram_message_id")
            if not isinstance(telegram_message_id, int):
                raise ValueError('"telegram_message_id" must be an integer')
            text = _require_str(args, "text")
            result = await api.reply_to_message(
                chat_id=chat_id,
                telegram_message_id=telegram_message_id,
                text=text,
            )
            return format_send_result(result, "Reply sent")

        elif name == "search_today_requests":
            query = _require_str(args, "query")
            limit = _optional_int(args, "limit", default=20, minimum=1, maximum=100)
            from datetime import UTC

            today = datetime.now(UTC).date()
            result = await api.search_messages(
                query=query,
                limit=limit,
                date_from=datetime(today.year, today.month, today.day, tzinfo=UTC),
            )
            return format_search_results(result)

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except ValueError as e:
        return _error(str(e))
    except Exception as e:
        return _error(str(e))
    finally:
        if api is not None:
            await api.close()


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
        chat_id = r.get("chat_id", "")
        msg_id = r.get("telegram_message_id", "")
        lines.append(
            f"[{chat_title}] {sender}: {text}\n"
            f"  - Sent: {sent_at} | Relevance: {similarity:.0f}% | Chat ID: {chat_id} | msg#{msg_id}\n"
        )
    return [TextContent(type="text", text="\n".join(lines))]


def _freshness_label(last_sync_at: Any, listener_active: bool = False) -> str:
    """Compute freshness label from last_sync_at timestamp."""
    if not last_sync_at:
        return "NEVER"
    try:
        if isinstance(last_sync_at, str):
            sync_dt = datetime.fromisoformat(last_sync_at)
        elif isinstance(last_sync_at, datetime):
            sync_dt = last_sync_at
        else:
            return "NEVER"
        from datetime import UTC, timedelta

        now = datetime.now(UTC)
        # Ensure sync_dt is timezone-aware
        if sync_dt.tzinfo is None:
            sync_dt = sync_dt.replace(tzinfo=UTC)
        age = now - sync_dt
        if listener_active and age < timedelta(minutes=5):
            return "LIVE"
        if age < timedelta(hours=1):
            return "FRESH"
        return "STALE"
    except (ValueError, TypeError):
        return "NEVER"


def format_chat_list(result: dict, listener_active: bool = False) -> list[TextContent]:
    """Format chat list for display."""
    if not result.get("chats"):
        return [TextContent(type="text", text="No chats synced yet.")]

    chats = result.get("chats", [])
    total = result.get("total", len(chats))
    lines = [f"Showing {len(chats)} of {total} total chats:\n"]
    for chat in chats:
        synced = chat.get("total_messages_synced", 0)
        title = chat.get("title", "Unknown")
        chat_type = chat.get("chat_type", "unknown")
        chat_id = chat.get("id", "unknown")
        last_sync = chat.get("last_sync_at")
        freshness = _freshness_label(last_sync, listener_active)
        sync_info = f"Last synced: {_format_date(last_sync)}" if last_sync else "Never synced"
        lines.append(
            f"- {title} ({chat_type}) [{freshness}]\n  ID: {chat_id} | Messages synced: {synced} | {sync_info}\n"
        )

    has_more = result.get("has_more", False)
    next_cursor = result.get("next_cursor")
    if has_more and next_cursor:
        lines.append(
            f'\n--- More chats available. Use cursor="{next_cursor}" to load the next page ---'
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
        msg_id = msg.get("telegram_message_id", "")
        lines.append(f"[{sent_at}] {sender} (msg#{msg_id}): {text}\n")

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


def format_data_status(settings: dict, chats_result: dict) -> list[TextContent]:
    """Format compact data status overview for display."""
    listener_active = settings.get("listener_active", False)
    realtime_sync = settings.get("realtime_sync_enabled", False)

    lines = [
        "Telegram Data Status\n",
        "=" * 40 + "\n",
        f"Real-time sync enabled: {realtime_sync}",
        f"Listener active: {listener_active}\n",
    ]

    chats = chats_result.get("chats", [])
    total_chats = chats_result.get("total", len(chats))
    if not chats:
        lines.append("No chats synced yet. Use sync_chat to download messages.")
    else:
        # Summary stats
        total_messages = sum(c.get("total_messages_synced", 0) for c in chats)
        type_counts: dict[str, int] = {}
        freshness_counts: dict[str, int] = {"LIVE": 0, "FRESH": 0, "STALE": 0, "NEVER": 0}
        for chat in chats:
            ct = chat.get("chat_type", "unknown")
            type_counts[ct] = type_counts.get(ct, 0) + 1
            freshness = _freshness_label(chat.get("last_sync_at"), listener_active)
            freshness_counts[freshness] = freshness_counts.get(freshness, 0) + 1

        lines.append(f"Total chats: {total_chats}")
        lines.append(f"Total messages synced: {total_messages:,}\n")

        # Type breakdown
        type_parts = [f"{v} {k}" for k, v in sorted(type_counts.items(), key=lambda x: -x[1])]
        lines.append(f"Chat types: {', '.join(type_parts)}\n")

        # Freshness distribution
        freshness_parts = []
        for label in ("LIVE", "FRESH", "STALE", "NEVER"):
            count = freshness_counts.get(label, 0)
            if count > 0:
                freshness_parts.append(f"{count} {label}")
        lines.append(f"Data freshness: {', '.join(freshness_parts)}\n")

        # Top 10 most recently active chats
        sorted_chats = sorted(
            chats,
            key=lambda c: c.get("last_sync_at") or "",
            reverse=True,
        )
        top_chats = sorted_chats[:10]
        lines.append(f"Top {len(top_chats)} most recently active chats:\n")
        for chat in top_chats:
            title = chat.get("title", "Unknown")
            chat_type = chat.get("chat_type", "unknown")
            chat_id = chat.get("id", "unknown")
            synced = chat.get("total_messages_synced", 0)
            freshness = _freshness_label(chat.get("last_sync_at"), listener_active)
            lines.append(
                f"- {title} ({chat_type}) [{freshness}] | ID: {chat_id} | Messages: {synced}"
            )

        lines.append(
            "\nUse list_chats to browse all chats, or search_messages to find specific content."
        )

    return [TextContent(type="text", text="\n".join(lines))]


def format_send_result(result: dict, action: str) -> list[TextContent]:
    """Format send/reply result for display."""
    msg_id = result.get("telegram_message_id", "unknown")
    chat_id = result.get("chat_id", "unknown")
    lines = [
        f"{action} successfully.\n",
        f"Message ID: {msg_id}",
        f"Chat ID: {chat_id}",
    ]
    file_name = result.get("file_name")
    if file_name:
        lines.append(f"File: {file_name}")
    text = result.get("text")
    if text:
        lines.append(f"Text: {text[:200]}")
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
    messages_seen = result.get("messages_seen")
    messages_total = result.get("messages_total")
    progress = result.get("progress_percent")
    error = result.get("error_message")

    lines = [
        f"Sync Job: {job_id}\n",
        f"Status: {status}\n",
    ]
    if messages_seen is not None and messages_total is not None:
        lines.append(
            f"Progress: {messages_seen:,} of {messages_total:,} messages ({progress:.0f}%)\n"
            if progress is not None
            else f"Progress: {messages_seen:,} of {messages_total:,} messages\n"
        )
    elif messages_seen is not None:
        lines.append(f"Progress: {messages_seen:,} messages fetched\n")
    elif progress is not None:
        lines.append(f"Progress: {progress}%\n")
    lines.append(f"Messages saved: {messages_processed:,}\n")
    if error:
        lines.append(f"Error: {error}\n")
    if status == "in_progress":
        lines.append("\nSync is still running. Check again in 10-15 seconds.")
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
