"""find_files reaches files through the conversation around them."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest


async def _chat_with_messages(db_session, test_user):
    from app.models.chat import ChatType, TelegramChat
    from app.models.message import TelegramMessage

    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=5001,
        chat_type=ChatType.PRIVATE,
        title="Андрей Лисицын",
    )
    db_session.add(chat)
    await db_session.flush()

    rows = [
        (100, "Скинь смету по стройке, пожалуйста", False, None, None),
        (101, None, True, "document", "smeta-2026.pdf"),
        (102, "Спасибо!", False, None, None),
        (140, None, True, "photo", None),
        (300, None, True, "document", "unrelated-invoice.pdf"),
    ]
    for tmid, text, has_media, media_type, file_name in rows:
        db_session.add(
            TelegramMessage(
                chat_id=chat.id,
                telegram_message_id=tmid,
                text=text,
                has_media=has_media,
                media_type=media_type,
                media_file_name=file_name,
                sender_id=777,
                sender_name="Андрей",
                is_outgoing=False,
                sent_at=datetime(2026, 3, 14, tzinfo=UTC),
            )
        )
    await db_session.flush()
    return chat


def _search_returning(chat, telegram_message_id, text):
    from app.schemas.search import SearchResponse, SearchResultItem

    item = SearchResultItem(
        id=chat.id,
        chat_id=chat.id,
        chat_title=chat.title,
        telegram_message_id=telegram_message_id,
        text=text,
        sender_name="Андрей",
        is_outgoing=False,
        sent_at=datetime(2026, 3, 14, tzinfo=UTC),
        similarity=0.9,
    )
    return SearchResponse(results=[item], query="смета", total=1)


async def _run(db_session, test_user, chat, **kwargs):
    from app.services import file_search_service

    with patch.object(
        file_search_service,
        "semantic_search",
        new_callable=AsyncMock,
        return_value=_search_returning(chat, 100, "Скинь смету по стройке, пожалуйста"),
    ):
        return await file_search_service.find_files(
            db_session, test_user.id, query="смета по стройке", **kwargs
        )


async def test_returns_the_file_sent_next_to_the_matching_message(
    db_session, test_user
):
    chat = await _chat_with_messages(db_session, test_user)
    result = await _run(db_session, test_user, chat)

    names = [f["file_name"] for f in result["files"]]
    assert "smeta-2026.pdf" in names


async def test_far_away_files_are_not_dragged_in(db_session, test_user):
    chat = await _chat_with_messages(db_session, test_user)
    result = await _run(db_session, test_user, chat)

    names = [f["file_name"] for f in result["files"]]
    assert "unrelated-invoice.pdf" not in names


async def test_reports_why_each_file_was_returned(db_session, test_user):
    chat = await _chat_with_messages(db_session, test_user)
    result = await _run(db_session, test_user, chat)

    match = next(f for f in result["files"] if f["file_name"] == "smeta-2026.pdf")
    assert "смету" in match["matched_because"]
    assert match["matched_distance"] == 1
    assert match["is_direct_match"] is False


async def test_photos_without_a_name_are_reachable_by_context(db_session, test_user):
    """The whole point: a photo has no filename and no caption to search."""
    chat = await _chat_with_messages(db_session, test_user)
    result = await _run(db_session, test_user, chat, context_window=40)

    assert any(f["media_type"] == "photo" for f in result["files"])


async def test_media_types_filter_is_honoured(db_session, test_user):
    chat = await _chat_with_messages(db_session, test_user)
    result = await _run(
        db_session, test_user, chat, media_types=["document"], context_window=40
    )

    assert {f["media_type"] for f in result["files"]} == {"document"}


async def test_window_of_zero_keeps_only_direct_matches(db_session, test_user):
    chat = await _chat_with_messages(db_session, test_user)
    result = await _run(db_session, test_user, chat, context_window=0)

    assert result["files"] == []


async def test_no_search_hits_yields_no_files(db_session, test_user):
    from app.schemas.search import SearchResponse
    from app.services import file_search_service

    await _chat_with_messages(db_session, test_user)
    with patch.object(
        file_search_service,
        "semantic_search",
        new_callable=AsyncMock,
        return_value=SearchResponse(results=[], query="x", total=0),
    ):
        result = await file_search_service.find_files(
            db_session, test_user.id, query="x"
        )

    assert result == {"files": [], "query": "x", "total": 0, "searched_messages": 0}


async def test_unstaged_file_still_carries_a_locator_to_fetch_it(db_session, test_user):
    """A private chat has no public t.me link, so the locator is the only route."""
    chat = await _chat_with_messages(db_session, test_user)
    result = await _run(db_session, test_user, chat)

    match = next(f for f in result["files"] if f["file_name"] == "smeta-2026.pdf")
    assert match["download_url"] is None
    assert match["telegram_url"] is None
    assert match["chat_id"] and match["telegram_message_id"] == 101


@pytest.mark.parametrize("window", [-5, 10_000])
async def test_context_window_is_clamped(db_session, test_user, window):
    chat = await _chat_with_messages(db_session, test_user)
    result = await _run(db_session, test_user, chat, context_window=window)

    assert isinstance(result["files"], list)


async def test_a_photo_with_no_caption_still_explains_itself(db_session, test_user):
    """Without this the result is "(no name)" and nothing a person can judge."""
    chat = await _chat_with_messages(db_session, test_user)
    result = await _run(db_session, test_user, chat, context_window=40)

    photo = next(f for f in result["files"] if f["media_type"] == "photo")
    assert photo["matched_because"], "a photo must carry the conversation around it"


async def test_a_file_that_matched_directly_quotes_its_neighbour(db_session, test_user):
    from app.services import file_search_service

    chat = await _chat_with_messages(db_session, test_user)
    # The document itself is the hit, and it has no caption of its own.
    with patch.object(
        file_search_service,
        "semantic_search",
        new_callable=AsyncMock,
        return_value=_search_returning(chat, 101, None),
    ):
        result = await file_search_service.find_files(
            db_session, test_user.id, query="смета"
        )

    match = next(f for f in result["files"] if f["file_name"] == "smeta-2026.pdf")
    assert match["is_direct_match"] is True
    assert "смету" in match["matched_because"]
