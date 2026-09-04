"""get_files hands an agent the metadata to judge a file and the link to fetch it."""

from unittest.mock import AsyncMock, patch

import pytest
from mcp.types import ResourceLink
from telegram_wai_mcp import server

BASE_URL = "https://telegram.waiwai.is"
CHAT_ID = "11111111-1111-1111-1111-111111111111"


def _entry(**overrides):
    entry = {
        "message_id": "22222222-2222-2222-2222-222222222222",
        "chat_id": CHAT_ID,
        "chat_title": "Love Letters Israel",
        "chat_type": "supergroup",
        "telegram_message_id": 4821,
        "sent_at": "2026-03-14T09:15:00+00:00",
        "sender_id": 777,
        "sender_name": "Диана",
        "is_outgoing": False,
        "media_type": "document",
        "media_file_name": "smeta-2026.pdf",
        "media_mime_type": "application/pdf",
        "media_file_size": 1_258_291,
        "media_duration_seconds": None,
        "media_sha256": "c" * 64,
        "caption": None,
        "content_summary": "Смета на ремонт кухни",
        "download_state": "ready",
        "media_download_url": f"/api/v1/chats/{CHAT_ID}/messages/4821/media?token=abc",
        "download_url_expires_at": "2026-03-14T10:15:00+00:00",
        "media_cache_status": "ready",
        "media_cache_stage": "complete",
        "media_cached_bytes": 1_258_291,
        "media_processing_status": "ready",
        "error_code": None,
        "error_detail": None,
        "retry_after": None,
        "telegram_message_url": "https://t.me/c/1234567890/4821",
        "matched_because": None,
        "matched_distance": None,
        "is_direct_match": None,
        "next_action": "Download media_download_url before 2026-03-14T10:15:00+00:00.",
    }
    entry.update(overrides)
    return entry


def _result(files, **overrides):
    counts = {"ready": 0, "fetching": 0, "queued": 0, "not_prepared": 0, "unavailable": 0}
    for entry in files:
        counts[entry["download_state"]] += 1
    result = {
        "files": files,
        "mode": "browse",
        "query": None,
        "total": len(files),
        "matched_total": len(files),
        "counts": counts,
        "has_more": False,
        "next_cursor": None,
        "truncated": False,
        "searched_messages": 0,
        "not_found": [],
        "filters_applied": {},
        "prepare": {"requested": False, "enqueued": 0, "error_code": None},
        "next_action": "Download the links now; they expire in 60 minutes.",
    }
    result.update(overrides)
    return result


def _render(result):
    content = server.format_file_results(result, BASE_URL)
    text = next(item.text for item in content if hasattr(item, "text"))
    links = [item for item in content if isinstance(item, ResourceLink)]
    return text, links


def test_get_files_emits_one_resource_link_per_ready_file():
    """The point of the rewrite: find_files never produced a single resource link."""
    text, links = _render(
        _result([_entry(), _entry(media_file_name="deck.pptx", telegram_message_id=4822)])
    )

    assert len(links) == 2
    assert links[0].name == "smeta-2026.pdf"
    assert str(links[0].uri).startswith(f"{BASE_URL}/api/v1/chats/")
    assert links[0].mimeType == "application/pdf"
    assert links[0].size == 1_258_291
    assert "Found 2 files. 2 ready to download." in text


def test_a_file_with_no_bytes_yet_produces_no_resource_link():
    """A link to a file that is not staged would 404 and read as a broken tool."""
    text, links = _render(
        _result(
            [
                _entry(
                    download_state="not_prepared",
                    media_download_url=None,
                    download_url_expires_at=None,
                    media_sha256=None,
                    next_action=("Call get_files again with prepare=true to fetch this file."),
                )
            ]
        )
    )

    assert links == []
    assert "NOT PREPARED" in text
    assert "Next: Call get_files again with prepare=true" in text


def test_the_listing_shows_state_size_and_when_the_link_expires():
    text, _links = _render(_result([_entry()]))

    assert "[Document] smeta-2026.pdf | 1.2 MB | application/pdf" in text
    assert "READY" in text
    assert "Link expires: 2026-03-14T10:15:00+00:00" in text
    assert "Chat ID: 11111111-1111-1111-1111-111111111111" in text
    assert "msg#4821" in text
    assert "Summary: Смета на ремонт кухни" in text


def test_a_voice_note_shows_its_length():
    text, _links = _render(
        _result(
            [
                _entry(
                    media_type="voice",
                    media_file_name=None,
                    media_mime_type="audio/ogg",
                    media_file_size=1_887_436,
                    media_duration_seconds=252,
                    content_summary=None,
                    caption="вот счёт за материалы",
                )
            ]
        )
    )

    assert "[Voice message] (no filename) | 1.8 MB | audio/ogg | 4:12" in text
    assert "Caption: вот счёт за материалы" in text


def test_an_unavailable_file_says_the_original_is_gone():
    text, links = _render(
        _result(
            [
                _entry(
                    download_state="unavailable",
                    media_download_url=None,
                    download_url_expires_at=None,
                    media_sha256=None,
                    error_code="source_deleted",
                    next_action=(
                        "The original was deleted from Telegram. No download is possible."
                    ),
                )
            ]
        )
    )

    assert links == []
    assert "UNAVAILABLE" in text
    assert "Error: source_deleted" in text
    assert "No download is possible" in text


def test_a_browse_page_prints_the_cursor_footer():
    text, _links = _render(_result([_entry()], has_more=True, next_cursor="eyJpZCI6ImE5In0"))

    assert '--- More files available. Use cursor="eyJpZCI6ImE5In0"' in text


def test_a_truncated_relevance_page_says_to_raise_the_limit_not_to_paginate():
    text, _links = _render(
        _result(
            [_entry(matched_because="Скинь смету", matched_distance=1)],
            mode="query",
            query="смета",
            truncated=True,
            matched_total=9,
        )
    )

    assert "cursor" not in text.split("---")[-1]
    assert "9 files matched and 1 were returned" in text
    assert "Matched: Скинь смету" in text


def test_an_empty_listing_says_so_without_resource_links():
    text, links = _render(_result([], next_action="No files matched."))

    assert links == []
    assert text.startswith("No files found for these filters.")

    text, _links = _render(
        _result([], mode="query", query="смета", next_action="No files matched.")
    )
    assert text.startswith('No files found for query: "смета".')


def test_a_stale_locator_is_named_in_the_output():
    text, _links = _render(
        _result(
            [_entry()],
            mode="locators",
            not_found=[{"chat_id": CHAT_ID, "telegram_message_id": 999}],
        )
    )

    assert f"Not found: chat {CHAT_ID} msg#999" in text


@pytest.mark.asyncio
async def test_get_files_renders_through_call_tool():
    api = AsyncMock()
    api.execute_data_tool = AsyncMock(return_value=_result([_entry()]))
    api.close = AsyncMock()

    with patch.object(server, "get_client", return_value=api):
        content = await server.call_tool("get_files", {"chat_ids": [CHAT_ID]})

    text = next(item.text for item in content if hasattr(item, "text"))
    assert "smeta-2026.pdf" in text
    assert any(isinstance(item, ResourceLink) for item in content)


@pytest.mark.asyncio
async def test_send_file_tells_the_caller_to_carry_the_name_across():
    """A signed media URL ends in /media, so the file would arrive named "media"."""
    api = AsyncMock()
    api.list_data_tools = AsyncMock(return_value={"tools": []})
    api.close = AsyncMock()

    with patch.object(server, "get_client", return_value=api):
        tools = await server.list_tools()

    send_file = next(tool for tool in tools if tool.name == "send_file")
    assert "media_file_name" in send_file.description
    assert "file_name" in send_file.inputSchema["properties"]
    assert "media_file_name" in send_file.inputSchema["properties"]["file_name"]["description"]


def test_stale_locators_are_named_even_when_nothing_resolved():
    """All locators stale is exactly when the caller most needs to know which."""
    text, links = _render(
        _result(
            [],
            mode="locators",
            not_found=[
                {"chat_id": CHAT_ID, "telegram_message_id": 999},
                {"chat_id": CHAT_ID, "telegram_message_id": 1000},
            ],
            next_action="No files matched.",
        )
    )

    assert links == []
    assert text.startswith("None of the requested messages carry a file any more.")
    assert f"Not found: chat {CHAT_ID} msg#999" in text
    assert f"Not found: chat {CHAT_ID} msg#1000" in text
