"""Inline Mode — the viral mechanic.

Type @waicomputer_bot <query> in ANY Telegram chat.
Wai searches your message history and returns results as inline articles.
You tap one → it's pasted into the chat → everyone sees.

This is how the product spreads organically:
1. You use inline in a group chat
2. Others see "Powered by @waicomputer_bot"
3. They try it themselves
4. Viral loop

Inline queries are handled via Telegram's answerInlineQuery API.
"""

import hashlib
import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

MAX_INLINE_RESULTS = 5


async def handle_inline_query(inline_query: dict) -> None:
    """Handle an inline query from Telegram.

    Called when user types @waicomputer_bot <query> in any chat.
    """
    query_id = inline_query["id"]
    query_text = inline_query.get("query", "").strip()
    from_user = inline_query.get("from", {})

    if not query_text or len(query_text) < 2:
        # Show help when query is empty
        await _answer_inline(
            query_id,
            [
                _make_article(
                    title="🔍 Search your messages",
                    description="Type a query to search your Telegram history by meaning",
                    text="💡 *Tip:* Type `@waicomputer_bot <your query>` in any chat to search your message history.\n\nExample: `@waicomputer_bot what did Alex say about pricing`",
                ),
            ],
        )
        return

    # Search user's messages
    try:
        results = await _search_for_inline(query_text, from_user.get("id"))
        if results:
            await _answer_inline(query_id, results)
        else:
            await _answer_inline(
                query_id,
                [
                    _make_article(
                        title=f"No results for: {query_text[:50]}",
                        description="Try a different query or connect your Telegram history first",
                        text=f"🔍 No messages found matching: _{query_text}_\n\nConnect your Telegram history at @waicomputer\\_bot to enable search.",
                    ),
                ],
            )
    except Exception as e:
        logger.error(f"Inline query failed: {e}", exc_info=True)
        await _answer_inline(
            query_id,
            [
                _make_article(
                    title="Search temporarily unavailable",
                    description="Please try again in a moment",
                    text="⚠️ Search is temporarily unavailable. Please try again.",
                ),
            ],
        )


async def _search_for_inline(query: str, telegram_user_id: int | None) -> list[dict]:
    """Search messages and format as inline results."""
    # TODO: Map telegram_user_id to internal user_id via DB lookup
    # For now, use placeholder user_id
    from uuid import UUID

    from app.core.database import async_session_factory
    from app.schemas.search import SearchRequest
    from app.services.search_service import semantic_search

    user_id = UUID("00000000-0000-0000-0000-000000000000")  # Placeholder

    request = SearchRequest(query=query, limit=MAX_INLINE_RESULTS)

    async with async_session_factory() as db:
        search_results = await semantic_search(db, user_id, request)

    articles = []
    for r in search_results.results:
        sender = r.sender_name or "Unknown"
        chat_title = r.chat_title or "Chat"
        date_str = r.sent_at.strftime("%b %d, %H:%M") if r.sent_at else ""
        text_preview = (r.text or "")[:200]

        # Build the message that will be pasted into the chat
        message_text = (
            f"💬 *{sender}* in _{chat_title}_ ({date_str}):\n"
            f"{text_preview}\n\n"
            f"_Found by @waicomputer\\_bot_"
        )

        articles.append(
            _make_article(
                title=f"{sender} — {text_preview[:60]}",
                description=f"{chat_title} · {date_str}",
                text=message_text,
            )
        )

    return articles


def _make_article(title: str, description: str, text: str) -> dict:
    """Create an InlineQueryResultArticle."""
    # Generate unique ID from content
    article_id = hashlib.md5(f"{title}{description}".encode()).hexdigest()[:16]

    return {
        "type": "article",
        "id": article_id,
        "title": title[:64],
        "description": description[:128],
        "input_message_content": {
            "message_text": text[:4096],
            "parse_mode": "Markdown",
        },
    }


async def _answer_inline(query_id: str, results: list[dict]) -> None:
    """Send inline query results back to Telegram."""
    import os

    token = os.environ.get("TELEGRAM_BOT_TOKEN") or get_settings().telegram_bot_token
    if not token:
        logger.error("No bot token for inline answer")
        return

    url = f"https://api.telegram.org/bot{token}/answerInlineQuery"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            url,
            json={
                "inline_query_id": query_id,
                "results": results,
                "cache_time": 30,  # Cache for 30 seconds
                "is_personal": True,  # Results are personal to each user
            },
        )
        if resp.status_code != 200:
            logger.error(f"answerInlineQuery failed: {resp.status_code} {resp.text}")
