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


def get_client() -> TelegramAIClient:
    global client
    if client is None:
        client = TelegramAIClient()
    return client


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
            name="get_recent_messages",
            description="Get recent messages from a specific chat or all chats.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "string",
                        "description": "Optional: Chat ID to get messages from",
                    },
                    "hours": {
                        "type": "integer",
                        "description": "How many hours back to look (default: 24)",
                        "default": 24,
                    },
                },
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
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    api = get_client()

    try:
        if name == "search_messages":
            result = await api.search_messages(
                query=arguments["query"],
                chat_ids=[arguments["chat_id"]] if arguments.get("chat_id") else None,
                limit=arguments.get("limit", 20),
            )
            return format_search_results(result)

        elif name == "list_chats":
            result = await api.list_chats(
                chat_type=arguments.get("chat_type"),
            )
            return format_chat_list(result)

        elif name == "get_recent_messages":
            result = await api.get_recent_messages(
                chat_id=arguments.get("chat_id"),
                hours=arguments.get("hours", 24),
            )
            return format_messages(result)

        elif name == "get_daily_digest":
            digest_date = None
            if arguments.get("date"):
                digest_date = date.fromisoformat(arguments["date"])
            result = await api.get_daily_digest(digest_date)
            return format_digest(result)

        elif name == "get_chat_summary":
            result = await api.get_chat_summary(
                chat_id=arguments["chat_id"],
                days=arguments.get("days", 7),
            )
            return format_chat_summary(result)

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


def format_search_results(result: dict) -> list[TextContent]:
    """Format search results for display."""
    if not result.get("results"):
        return [TextContent(type="text", text="No messages found matching your query.")]

    lines = [f"Found {result['total']} messages for query: \"{result['query']}\"\n"]
    for r in result["results"]:
        sender = r.get("sender_name", "You" if r["is_outgoing"] else "Unknown")
        text = (r.get("text") or "")[:200]
        similarity = r.get("similarity", 0) * 100
        lines.append(
            f"[{r['chat_title']}] {sender}: {text}\n"
            f"  - Sent: {r['sent_at'][:10]} | Relevance: {similarity:.0f}%\n"
        )
    return [TextContent(type="text", text="\n".join(lines))]


def format_chat_list(result: dict) -> list[TextContent]:
    """Format chat list for display."""
    if not result.get("chats"):
        return [TextContent(type="text", text="No chats synced yet.")]

    lines = [f"Your Telegram Chats ({result['total']} total):\n"]
    for chat in result["chats"]:
        synced = chat.get("total_messages_synced", 0)
        lines.append(
            f"• {chat['title']} ({chat['chat_type']})\n"
            f"  ID: {chat['id']} | Messages: {synced}\n"
        )
    return [TextContent(type="text", text="\n".join(lines))]


def format_messages(messages: list) -> list[TextContent]:
    """Format message list for display."""
    if not messages:
        return [TextContent(type="text", text="No recent messages found.")]

    lines = ["Recent Messages:\n"]
    for msg in messages:
        sender = msg.get("sender_name", "You" if msg.get("is_outgoing") else "Unknown")
        text = (msg.get("text") or "[media]")[:200]
        lines.append(f"[{msg.get('chat_title', 'Unknown')}] {sender}: {text}\n")
    return [TextContent(type="text", text="\n".join(lines))]


def format_digest(result: dict) -> list[TextContent]:
    """Format digest for display."""
    lines = [
        f"Daily Digest for {result['digest_date']}\n",
        "=" * 40 + "\n",
        result["content"],
        "\n" + "=" * 40,
        f"\nStats: {result.get('summary_stats', {})}",
    ]
    return [TextContent(type="text", text="\n".join(lines))]


def format_chat_summary(result: dict) -> list[TextContent]:
    """Format chat summary for display."""
    chat = result.get("chat", {})
    lines = [
        f"Chat Summary: {chat.get('title', 'Unknown')}\n",
        f"Period: Last {result['period_days']} days\n",
        f"Messages: {result['message_count']}\n",
        "\nRecent messages:\n",
    ]
    for msg in result.get("messages", [])[:10]:
        sender = msg.get("sender_name", "Unknown")
        text = (msg.get("text") or "[media]")[:100]
        lines.append(f"• {sender}: {text}\n")
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
