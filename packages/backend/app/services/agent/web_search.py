"""Web search for digital agents via DuckDuckGo Instant Answers API.

No API key required. Returns structured results for Claude to reason over.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

DUCKDUCKGO_API_URL = "https://api.duckduckgo.com/"
SEARCH_TIMEOUT = 10.0  # seconds


async def search_web(query: str) -> str:
    """Search the web via DuckDuckGo and return formatted results.

    Uses the Instant Answers API (free, no key).
    Returns a text summary suitable for injection into Claude context.
    """
    async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
        response = await client.get(
            DUCKDUCKGO_API_URL,
            params={
                "q": query,
                "format": "json",
                "no_html": "1",
                "skip_disambig": "1",
            },
        )
        response.raise_for_status()
        data = response.json()

    return _format_results(query, data)


def _format_results(query: str, data: dict) -> str:
    """Format DuckDuckGo API response into readable text."""
    sections: list[str] = []

    # Abstract (main answer)
    abstract = data.get("AbstractText", "")
    abstract_source = data.get("AbstractSource", "")
    abstract_url = data.get("AbstractURL", "")
    if abstract:
        source_info = f" (source: {abstract_source})" if abstract_source else ""
        url_info = f"\n{abstract_url}" if abstract_url else ""
        sections.append(f"**Summary**{source_info}:\n{abstract}{url_info}")

    # Answer (direct factual answer)
    answer = data.get("Answer", "")
    if answer:
        sections.append(f"**Answer**: {answer}")

    # Related topics (search results)
    topics = data.get("RelatedTopics", [])
    if topics:
        topic_lines = []
        for topic in topics[:8]:  # Max 8 results
            text = topic.get("Text", "")
            url = topic.get("FirstURL", "")
            if text:
                entry = f"- {text}"
                if url:
                    entry += f"\n  {url}"
                topic_lines.append(entry)
            # Handle sub-topics (grouped results)
            sub_topics = topic.get("Topics", [])
            for sub in sub_topics[:3]:
                sub_text = sub.get("Text", "")
                sub_url = sub.get("FirstURL", "")
                if sub_text:
                    entry = f"- {sub_text}"
                    if sub_url:
                        entry += f"\n  {sub_url}"
                    topic_lines.append(entry)

        if topic_lines:
            sections.append("**Related results**:\n" + "\n".join(topic_lines[:10]))

    # Definition
    definition = data.get("Definition", "")
    if definition:
        sections.append(f"**Definition**: {definition}")

    if not sections:
        return f"No results found for: {query}"

    return "\n\n".join(sections)
