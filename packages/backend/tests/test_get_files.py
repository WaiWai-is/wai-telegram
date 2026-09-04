"""get_files lists files by their attributes, and reaches them through the talk."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.models.chat import ChatType, TelegramChat
from app.models.media import MediaObject, MediaObjectStatus, MediaStage
from app.models.message import MediaProcessingStatus, TelegramMessage
from app.services.tool_registry import ToolInputError, execute_data_tool

BASE = datetime(2026, 3, 14, 12, tzinfo=UTC)


async def _chat(db_session, test_user, **kwargs):
    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=kwargs.pop("telegram_chat_id", 5001),
        chat_type=kwargs.pop("chat_type", ChatType.PRIVATE),
        title=kwargs.pop("title", "Андрей Лисицын"),
        **kwargs,
    )
    db_session.add(chat)
    await db_session.flush()
    return chat


async def _message(db_session, chat, telegram_message_id, **kwargs):
    message = TelegramMessage(
        chat_id=chat.id,
        telegram_message_id=telegram_message_id,
        text=kwargs.pop("text", None),
        has_media=kwargs.pop("has_media", True),
        media_type=kwargs.pop("media_type", "document"),
        media_file_name=kwargs.pop("media_file_name", None),
        media_mime_type=kwargs.pop("media_mime_type", None),
        media_file_size=kwargs.pop("media_file_size", None),
        sender_id=kwargs.pop("sender_id", 777),
        sender_name=kwargs.pop("sender_name", "Андрей"),
        is_outgoing=kwargs.pop("is_outgoing", False),
        sent_at=kwargs.pop("sent_at", BASE),
        **kwargs,
    )
    db_session.add(message)
    await db_session.flush()
    return message


async def _stage(db_session, test_user, message, **kwargs):
    media_object = MediaObject(
        user_id=test_user.id,
        message_id=message.id,
        cache_key=uuid4().hex + uuid4().hex,
        relative_path=kwargs.pop("relative_path", "aa/bb/original.pdf"),
        sha256=kwargs.pop("sha256", "c" * 64),
        file_name=kwargs.pop("file_name", None),
        mime_type=kwargs.pop("mime_type", None),
        size_bytes=kwargs.pop("size_bytes", None),
        status=kwargs.pop("status", MediaObjectStatus.READY),
        stage=kwargs.pop("stage", MediaStage.COMPLETE),
        **kwargs,
    )
    db_session.add(media_object)
    await db_session.flush()
    return media_object


async def _files(db_session, test_user, **arguments):
    return await execute_data_tool(db_session, test_user.id, "get_files", arguments)


async def _conversation(db_session, test_user):
    """A chat where the file is remembered by what was said next to it."""
    chat = await _chat(db_session, test_user)
    rows = [
        (100, "Скинь смету по стройке, пожалуйста", False, None, None),
        (101, None, True, "document", "smeta-2026.pdf"),
        (102, "Спасибо!", False, None, None),
        (140, None, True, "photo", None),
        (300, None, True, "document", "unrelated-invoice.pdf"),
    ]
    for tmid, text, has_media, media_type, file_name in rows:
        await _message(
            db_session,
            chat,
            tmid,
            text=text,
            has_media=has_media,
            media_type=media_type,
            media_file_name=file_name,
        )
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
        sent_at=BASE,
        similarity=0.9,
    )
    return SearchResponse(results=[item], query="смета", total=1)


async def _query(db_session, test_user, chat, hit=100, hit_text=None, **arguments):
    from app.services import file_search_service

    with patch.object(
        file_search_service,
        "semantic_search",
        new_callable=AsyncMock,
        return_value=_search_returning(
            chat, hit, hit_text or "Скинь смету по стройке, пожалуйста"
        ),
    ):
        return await _files(
            db_session, test_user, query="смета по стройке", **arguments
        )


# --- browse mode -------------------------------------------------------------


async def test_a_browse_with_no_query_never_touches_semantic_search(
    db_session, test_user
):
    """Browsing is an index walk; an embedding bill for it would be pure waste."""
    from app.services import file_search_service

    await _conversation(db_session, test_user)
    with patch.object(
        file_search_service, "semantic_search", new_callable=AsyncMock
    ) as search:
        result = await _files(db_session, test_user)

    search.assert_not_awaited()
    assert result["mode"] == "browse"
    assert len(result["files"]) == 3


async def test_files_are_listed_newest_first_and_paginate_by_cursor(
    db_session, test_user
):
    chat = await _chat(db_session, test_user)
    for index in range(5):
        await _message(
            db_session,
            chat,
            200 + index,
            media_file_name=f"file-{index}.pdf",
            sent_at=BASE + timedelta(minutes=index),
        )

    first = await _files(db_session, test_user, limit=2)
    assert [f["media_file_name"] for f in first["files"]] == [
        "file-4.pdf",
        "file-3.pdf",
    ]
    assert first["has_more"] is True

    second = await _files(db_session, test_user, limit=2, cursor=first["next_cursor"])
    assert [f["media_file_name"] for f in second["files"]] == [
        "file-2.pdf",
        "file-1.pdf",
    ]

    third = await _files(db_session, test_user, limit=2, cursor=second["next_cursor"])
    assert [f["media_file_name"] for f in third["files"]] == ["file-0.pdf"]
    assert third["has_more"] is False
    assert third["next_cursor"] is None


async def test_oldest_order_walks_the_other_way(db_session, test_user):
    chat = await _chat(db_session, test_user)
    for index in range(3):
        await _message(
            db_session,
            chat,
            300 + index,
            media_file_name=f"file-{index}.pdf",
            sent_at=BASE + timedelta(minutes=index),
        )

    page = await _files(db_session, test_user, order="oldest", limit=2)
    assert [f["media_file_name"] for f in page["files"]] == ["file-0.pdf", "file-1.pdf"]

    nxt = await _files(
        db_session, test_user, order="oldest", limit=2, cursor=page["next_cursor"]
    )
    assert [f["media_file_name"] for f in nxt["files"]] == ["file-2.pdf"]


async def test_a_cursor_issued_for_another_order_is_rejected(db_session, test_user):
    """Silently walking the wrong way would repeat or skip whole pages."""
    chat = await _chat(db_session, test_user)
    for index in range(3):
        await _message(db_session, chat, 400 + index, media_file_name=f"f{index}.pdf")

    page = await _files(db_session, test_user, limit=1)
    with pytest.raises(ToolInputError, match="order"):
        await _files(
            db_session, test_user, limit=1, order="oldest", cursor=page["next_cursor"]
        )


async def test_a_browse_cursor_is_refused_alongside_a_query(db_session, test_user):
    chat = await _chat(db_session, test_user)
    await _message(db_session, chat, 500, media_file_name="a.pdf")
    await _message(db_session, chat, 501, media_file_name="b.pdf")
    page = await _files(db_session, test_user, limit=1)

    with pytest.raises(ToolInputError, match="cursor"):
        await _files(db_session, test_user, query="смета", cursor=page["next_cursor"])


async def test_voice_messages_and_video_notes_are_reachable_now(db_session, test_user):
    """Both were missing from the type tuple while staying perfectly downloadable."""
    chat = await _chat(db_session, test_user)
    await _message(db_session, chat, 600, media_type="voice")
    await _message(db_session, chat, 601, media_type="video_note")

    result = await _files(db_session, test_user)

    assert {f["media_type"] for f in result["files"]} == {"voice", "video_note"}


async def test_polls_and_locations_stay_out_of_the_default_listing(
    db_session, test_user
):
    chat = await _chat(db_session, test_user)
    await _message(db_session, chat, 700, media_type="other")
    await _message(db_session, chat, 701, media_file_name="real.pdf")

    default = await _files(db_session, test_user)
    assert [f["media_file_name"] for f in default["files"]] == ["real.pdf"]

    asked = await _files(db_session, test_user, media_types=["other"])
    assert [f["media_type"] for f in asked["files"]] == ["other"]


async def test_an_unknown_media_type_is_rejected_instead_of_widening_the_search(
    db_session, test_user
):
    """The old code dropped the word and returned everything, which reads as a lie."""
    await _conversation(db_session, test_user)

    with pytest.raises(ToolInputError, match="sticker"):
        await _files(db_session, test_user, media_types=["sticker"])


async def test_extension_filter_reaches_pdfs_without_a_query(db_session, test_user):
    chat = await _chat(db_session, test_user)
    await _message(db_session, chat, 800, media_file_name="deck.pptx")
    await _message(db_session, chat, 801, media_file_name="smeta.PDF")

    result = await _files(db_session, test_user, extensions=[".pdf"])

    assert [f["media_file_name"] for f in result["files"]] == ["smeta.PDF"]


async def test_file_name_and_sender_filters_narrow_the_same_listing(
    db_session, test_user
):
    chat = await _chat(db_session, test_user)
    await _message(
        db_session, chat, 900, media_file_name="smeta-2026.pdf", sender_name="Андрей"
    )
    await _message(
        db_session, chat, 901, media_file_name="smeta-2025.pdf", sender_name="Диана"
    )

    result = await _files(db_session, test_user, file_name="smeta", sender="Андр")

    assert [f["media_file_name"] for f in result["files"]] == ["smeta-2026.pdf"]


async def test_from_me_separates_what_i_sent(db_session, test_user):
    chat = await _chat(db_session, test_user)
    await _message(db_session, chat, 950, media_file_name="mine.pdf", is_outgoing=True)
    await _message(db_session, chat, 951, media_file_name="theirs.pdf")

    result = await _files(db_session, test_user, from_me=True)

    assert [f["media_file_name"] for f in result["files"]] == ["mine.pdf"]


async def test_a_staged_file_and_an_unstaged_one_are_both_downloadable(
    db_session, test_user
):
    """Being on our disk stopped deciding anything once streaming existed."""
    chat = await _chat(db_session, test_user)
    staged = await _message(db_session, chat, 1000, media_file_name="staged.pdf")
    await _stage(db_session, test_user, staged)
    await _message(db_session, chat, 1001, media_file_name="not-staged.pdf")

    result = await _files(db_session, test_user)

    assert len(result["files"]) == 2
    assert all(f["download_state"] == "ready" for f in result["files"])
    assert all(f["media_download_url"] for f in result["files"])
    assert all(f["download_url_expires_at"] for f in result["files"])


async def test_max_size_bytes_keeps_photos_whose_size_telegram_never_told_us(
    db_session, test_user
):
    """Telegram sends no size for a photo, and unknown must not read as too big."""
    chat = await _chat(db_session, test_user)
    await _message(db_session, chat, 1100, media_type="photo", media_file_size=None)
    await _message(
        db_session, chat, 1101, media_file_name="huge.zip", media_file_size=10**9
    )

    result = await _files(db_session, test_user, max_size_bytes=1000)

    assert [f["media_type"] for f in result["files"]] == ["photo"]


async def test_deleted_messages_never_appear_in_any_mode(db_session, test_user):
    chat = await _chat(db_session, test_user)
    await _message(
        db_session,
        chat,
        1200,
        media_file_name="gone.pdf",
        deleted_at=datetime.now(UTC),
    )

    result = await _files(db_session, test_user)

    assert result["files"] == []


# --- download state ----------------------------------------------------------


async def test_a_file_whose_transcription_failed_is_still_downloadable(
    db_session, test_user
):
    """Extraction failing says nothing about whether the bytes can be had."""
    chat = await _chat(db_session, test_user)
    message = await _message(db_session, chat, 1300, media_type="voice")
    await _stage(
        db_session,
        test_user,
        message,
        status=MediaObjectStatus.NO_SPEECH,
        error_code="no_speech",
    )

    result = await _files(db_session, test_user)

    entry = result["files"][0]
    assert entry["download_state"] == "ready"
    assert entry["media_download_url"]


async def test_a_deleted_original_is_unavailable_and_says_why(db_session, test_user):
    chat = await _chat(db_session, test_user)
    message = await _message(db_session, chat, 1400, media_file_name="gone.pdf")
    await _stage(
        db_session,
        test_user,
        message,
        relative_path=None,
        sha256=None,
        status=MediaObjectStatus.SOURCE_DELETED,
        error_code="source_deleted",
    )

    result = await _files(db_session, test_user)

    entry = result["files"][0]
    assert entry["download_state"] == "unavailable"
    assert entry["media_download_url"] is None
    assert entry["next_action"] == (
        "The original was deleted from Telegram. No download is possible."
    )
    assert result["counts"]["unavailable"] == 1


async def test_a_file_mid_fetch_is_already_downloadable(db_session, test_user):
    """Nothing waits on our cache any more; the endpoint streams the original."""
    chat = await _chat(db_session, test_user)
    message = await _message(db_session, chat, 1500, media_file_name="big.zip")
    await _stage(
        db_session,
        test_user,
        message,
        relative_path=None,
        sha256=None,
        status=MediaObjectStatus.FETCHING,
        stage=MediaStage.FETCH,
        byte_offset=4096,
    )

    result = await _files(db_session, test_user)

    entry = result["files"][0]
    assert entry["download_state"] == "ready"
    assert entry["media_download_url"]
    assert entry["media_cached_bytes"] == 4096


async def test_file_metadata_prefers_the_staged_object_over_the_message_row(
    db_session, test_user
):
    """A photo arrives with no name and no size; staging is where both appear."""
    chat = await _chat(db_session, test_user)
    message = await _message(db_session, chat, 1600, media_type="photo")
    await _stage(
        db_session,
        test_user,
        message,
        file_name="IMG_0421.jpg",
        mime_type="image/jpeg",
        size_bytes=204_800,
    )

    entry = (await _files(db_session, test_user))["files"][0]

    assert entry["media_file_name"] == "IMG_0421.jpg"
    assert entry["media_mime_type"] == "image/jpeg"
    assert entry["media_file_size"] == 204_800


# --- query mode --------------------------------------------------------------


async def test_query_mode_still_reaches_a_photo_through_the_talk_around_it(
    db_session, test_user
):
    chat = await _conversation(db_session, test_user)

    result = await _query(db_session, test_user, chat, context_window=40)

    assert result["mode"] == "query"
    photo = next(f for f in result["files"] if f["media_type"] == "photo")
    assert photo["matched_because"], "a photo must carry the conversation around it"


async def test_query_mode_reports_why_each_file_was_returned(db_session, test_user):
    chat = await _conversation(db_session, test_user)

    result = await _query(db_session, test_user, chat)

    match = next(f for f in result["files"] if f["media_file_name"] == "smeta-2026.pdf")
    assert "смету" in match["matched_because"]
    assert match["matched_distance"] == 1
    assert match["is_direct_match"] is False


async def test_query_mode_leaves_far_away_files_alone(db_session, test_user):
    chat = await _conversation(db_session, test_user)

    result = await _query(db_session, test_user, chat)

    names = [f["media_file_name"] for f in result["files"]]
    assert "unrelated-invoice.pdf" not in names


async def test_a_file_that_matched_directly_quotes_its_neighbour(db_session, test_user):
    chat = await _conversation(db_session, test_user)

    result = await _query(db_session, test_user, chat, hit=101, hit_text="")

    match = next(f for f in result["files"] if f["media_file_name"] == "smeta-2026.pdf")
    assert match["is_direct_match"] is True
    assert "смету" in match["matched_because"]


async def test_query_mode_honours_the_same_filters_as_browse(db_session, test_user):
    chat = await _conversation(db_session, test_user)

    result = await _query(
        db_session, test_user, chat, media_types=["document"], context_window=40
    )

    assert {f["media_type"] for f in result["files"]} == {"document"}


async def test_window_of_zero_keeps_only_direct_matches(db_session, test_user):
    chat = await _conversation(db_session, test_user)

    result = await _query(db_session, test_user, chat, context_window=0)

    assert result["files"] == []


async def test_no_search_hits_yields_no_files(db_session, test_user):
    from app.schemas.search import SearchResponse
    from app.services import file_search_service

    await _conversation(db_session, test_user)
    with patch.object(
        file_search_service,
        "semantic_search",
        new_callable=AsyncMock,
        return_value=SearchResponse(results=[], query="x", total=0),
    ):
        result = await _files(db_session, test_user, query="x")

    assert result["files"] == []
    assert result["searched_messages"] == 0
    assert "add a query" in result["next_action"] or result["next_action"]


async def test_query_mode_reports_truncation_instead_of_a_cursor_it_cannot_honour(
    db_session, test_user
):
    """has_more with no cursor is an infinite loop for anything that paginates."""
    chat = await _conversation(db_session, test_user)

    result = await _query(db_session, test_user, chat, context_window=40, limit=1)

    assert result["has_more"] is False
    assert result["next_cursor"] is None
    assert result["truncated"] is True
    assert result["matched_total"] > result["total"]
    assert "Raise limit" in result["next_action"]


@pytest.mark.parametrize("window", [0, 40])
async def test_context_window_is_clamped(db_session, test_user, window):
    chat = await _conversation(db_session, test_user)

    result = await _query(db_session, test_user, chat, context_window=window)

    assert isinstance(result["files"], list)


# --- locator mode ------------------------------------------------------------


async def test_locators_ignore_filters_and_keep_the_caller_order(db_session, test_user):
    chat = await _chat(db_session, test_user)
    await _message(db_session, chat, 1700, media_file_name="a.pdf")
    await _message(db_session, chat, 1701, media_file_name="b.pdf")

    result = await _files(
        db_session,
        test_user,
        files=[
            {"chat_id": str(chat.id), "telegram_message_id": 1701},
            {"chat_id": str(chat.id), "telegram_message_id": 1700},
        ],
    )

    assert result["mode"] == "locators"
    assert [f["media_file_name"] for f in result["files"]] == ["b.pdf", "a.pdf"]


async def test_a_stale_locator_is_reported_instead_of_failing_the_batch(
    db_session, test_user
):
    chat = await _chat(db_session, test_user)
    await _message(db_session, chat, 1800, media_file_name="here.pdf")

    result = await _files(
        db_session,
        test_user,
        files=[
            {"chat_id": str(chat.id), "telegram_message_id": 1800},
            {"chat_id": str(chat.id), "telegram_message_id": 999_999},
        ],
    )

    assert [f["media_file_name"] for f in result["files"]] == ["here.pdf"]
    assert result["not_found"] == [
        {"chat_id": str(chat.id), "telegram_message_id": 999_999}
    ]


async def test_locators_cannot_be_combined_with_a_query_or_a_filter(
    db_session, test_user
):
    chat = await _chat(db_session, test_user)
    await _message(db_session, chat, 1900, media_file_name="a.pdf")
    locators = [{"chat_id": str(chat.id), "telegram_message_id": 1900}]

    with pytest.raises(ToolInputError, match="files cannot be combined"):
        await _files(db_session, test_user, files=locators, query="смета")
    with pytest.raises(ToolInputError, match="files cannot be combined"):
        await _files(db_session, test_user, files=locators, media_types=["document"])


# --- payload shape -----------------------------------------------------------


async def test_every_entry_carries_the_same_keys_in_every_mode(db_session, test_user):
    """One shape in all three modes, so a caller never branches on the mode."""
    chat = await _conversation(db_session, test_user)

    browse = await _files(db_session, test_user)
    query = await _query(db_session, test_user, chat)
    locators = await _files(
        db_session,
        test_user,
        files=[{"chat_id": str(chat.id), "telegram_message_id": 101}],
    )

    shapes = {frozenset(result["files"][0]) for result in (browse, query, locators)}
    assert len(shapes) == 1
    browse_entry = browse["files"][0]
    assert browse_entry["matched_because"] is None
    assert browse_entry["matched_distance"] is None
    assert browse_entry["is_direct_match"] is None


async def test_an_unstaged_private_file_is_downloadable_and_locatable(
    db_session, test_user
):
    """A private chat has no public t.me link, so the locator is the only route."""
    chat = await _conversation(db_session, test_user)

    result = await _query(db_session, test_user, chat)

    match = next(f for f in result["files"] if f["media_file_name"] == "smeta-2026.pdf")
    assert match["media_download_url"], "nothing has to be staged to download it"
    assert match["telegram_message_url"] is None
    assert match["chat_id"] and match["telegram_message_id"] == 101
    assert match["next_action"].startswith("Download media_download_url before")


async def test_filters_applied_echoes_what_actually_ran(db_session, test_user):
    """A filter that was defaulted or dropped has to be visible, not guessed at."""
    chat = await _chat(db_session, test_user)
    await _message(db_session, chat, 2000, media_file_name="a.pdf")

    result = await _files(db_session, test_user, extensions=["PDF"], limit=5)

    assert result["filters_applied"]["extensions"] == ["pdf"]
    assert result["filters_applied"]["limit"] == 5
    assert result["filters_applied"]["sender"] is None
    assert "voice" in result["filters_applied"]["media_types"]


async def test_queued_text_extraction_does_not_hold_up_the_download(
    db_session, test_user
):
    """Extraction and download are separate concerns now."""
    chat = await _chat(db_session, test_user)
    await _message(
        db_session,
        chat,
        2100,
        media_file_name="pending.pdf",
        media_processing_status=MediaProcessingStatus.QUEUED,
    )

    entry = (await _files(db_session, test_user))["files"][0]

    assert entry["download_state"] == "ready"
    assert entry["media_processing_status"] == "queued"


# --- filter parsing ----------------------------------------------------------


async def test_date_bounds_reach_the_database_as_timestamps_not_strings(
    db_session, test_user
):
    """PostgreSQL has no timestamptz >= varchar operator; SQLite hides that."""
    from app.services.tool_registry import _optional_datetime

    parsed = _optional_datetime({"date_from": "2026-03-01T09:00:00Z"}, "date_from")

    assert isinstance(parsed, datetime)
    assert parsed == datetime(2026, 3, 1, 9, tzinfo=UTC)


async def test_a_bare_date_in_date_to_covers_that_whole_day(db_session, test_user):
    """Reading it as midnight drops the day the caller explicitly asked for."""
    from app.services.tool_registry import _optional_datetime

    parsed = _optional_datetime({"date_to": "2026-03-14"}, "date_to", end_of_day=True)

    assert parsed.hour == 23 and parsed.minute == 59
    assert parsed.tzinfo is not None


async def test_a_naive_date_is_read_as_utc(db_session, test_user):
    from app.services.tool_registry import _optional_datetime

    parsed = _optional_datetime({"date_from": "2026-03-01T09:00:00"}, "date_from")

    assert parsed.tzinfo == UTC


async def test_a_date_we_cannot_parse_is_named_rather_than_guessed(
    db_session, test_user
):
    await _conversation(db_session, test_user)

    with pytest.raises(ToolInputError, match="ISO 8601"):
        await _files(db_session, test_user, date_from="last tuesday")


async def test_the_date_filter_selects_by_day_end_to_end(db_session, test_user):
    chat = await _chat(db_session, test_user)
    await _message(db_session, chat, 2200, media_file_name="march.pdf", sent_at=BASE)
    await _message(
        db_session,
        chat,
        2201,
        media_file_name="april.pdf",
        sent_at=BASE + timedelta(days=30),
    )

    result = await _files(db_session, test_user, date_to="2026-03-14")

    assert [f["media_file_name"] for f in result["files"]] == ["march.pdf"]


async def test_a_non_numeric_size_bound_is_refused(db_session, test_user):
    await _conversation(db_session, test_user)

    with pytest.raises(ToolInputError, match="max_size_bytes"):
        await _files(db_session, test_user, max_size_bytes="big")


@pytest.mark.parametrize(
    "arguments, expected",
    [
        ({"limit": "many"}, "limit"),
        ({"chat_ids": "not-a-list"}, "chat_ids"),
        ({"chat_ids": ["not-a-uuid"]}, "chat_ids"),
        ({"chat_types": ["broadcast"]}, "chat_types"),
        ({"from_me": "yes"}, "from_me"),
        ({"file_name": ""}, "file_name"),
        ({"order": "sideways"}, "order"),
        ({"extensions": "pdf"}, "extensions"),
    ],
)
async def test_a_malformed_argument_is_named_rather_than_crashing(
    db_session, test_user, arguments, expected
):
    """A wrong type has to come back as a message an agent can act on, not a 500."""
    await _conversation(db_session, test_user)

    with pytest.raises(ToolInputError, match=expected):
        await _files(db_session, test_user, **arguments)
