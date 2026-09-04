"""get_files with prepare=true stages a page of files without flooding the queue."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.models.chat import ChatType, TelegramChat
from app.models.media import MediaObject, MediaObjectStatus, MediaStage
from app.models.message import MediaProcessingStatus, TelegramMessage
from app.services.tool_registry import execute_data_tool

BASE = datetime(2026, 3, 14, 12, tzinfo=UTC)


async def _chat(db_session, test_user):
    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=7001,
        chat_type=ChatType.SUPERGROUP,
        title="Love Letters Israel",
        username="love_letters",
    )
    db_session.add(chat)
    await db_session.flush()
    return chat


async def _message(db_session, chat, telegram_message_id, **kwargs):
    message = TelegramMessage(
        chat_id=chat.id,
        telegram_message_id=telegram_message_id,
        has_media=True,
        media_type=kwargs.pop("media_type", "document"),
        media_file_name=kwargs.pop("media_file_name", f"f{telegram_message_id}.pdf"),
        media_file_size=kwargs.pop("media_file_size", 1024),
        sender_name="Андрей",
        is_outgoing=False,
        sent_at=BASE,
        **kwargs,
    )
    db_session.add(message)
    await db_session.flush()
    return message


async def _prepare(db_session, test_user, **arguments):
    return await execute_data_tool(
        db_session, test_user.id, "get_files", {"prepare": True, **arguments}
    )


def _roomy_disk():
    return patch(
        "app.services.tool_registry.shutil.disk_usage",
        return_value=SimpleNamespace(total=0, used=0, free=500 * 1024**3),
    )


def _enqueue_spy():
    return patch("app.tasks.media_tasks.enqueue_media_processing")


async def test_prepare_enqueues_the_whole_page_in_one_dispatch(db_session, test_user):
    """One dispatch of N ids, not N dispatches of one - the queue is concurrency 1."""
    chat = await _chat(db_session, test_user)
    for index in range(3):
        await _message(db_session, chat, 100 + index)

    with _roomy_disk(), _enqueue_spy() as enqueue:
        result = await _prepare(db_session, test_user)

    enqueue.assert_called_once()
    assert len(enqueue.call_args.args[0]) == 3
    assert result["prepare"]["enqueued"] == 3
    assert {f["download_state"] for f in result["files"]} == {"queued"}
    assert "60 seconds" in result["next_action"]


async def test_prepare_stages_only_files_that_nothing_is_fetching(
    db_session, test_user
):
    chat = await _chat(db_session, test_user)
    fresh = await _message(db_session, chat, 200)
    moving = await _message(db_session, chat, 201)
    db_session.add(
        MediaObject(
            user_id=test_user.id,
            message_id=moving.id,
            cache_key=uuid4().hex * 2,
            status=MediaObjectStatus.FETCHING,
            stage=MediaStage.FETCH,
        )
    )
    await db_session.flush()

    with _roomy_disk(), _enqueue_spy() as enqueue:
        result = await _prepare(db_session, test_user)

    assert enqueue.call_args.args[0] == [fresh.id]
    assert result["prepare"]["already_in_progress"] == 1


async def test_prepare_never_retries_a_file_telegram_deleted(db_session, test_user):
    """Otherwise a polling caller re-pushes a doomed file on every single call."""
    chat = await _chat(db_session, test_user)
    gone = await _message(db_session, chat, 300)
    db_session.add(
        MediaObject(
            user_id=test_user.id,
            message_id=gone.id,
            cache_key=uuid4().hex * 2,
            status=MediaObjectStatus.SOURCE_DELETED,
            error_code="source_deleted",
            stage=MediaStage.FETCH,
        )
    )
    await db_session.flush()

    with _roomy_disk(), _enqueue_spy() as enqueue:
        result = await _prepare(db_session, test_user)

    enqueue.assert_not_called()
    assert result["prepare"]["enqueued"] == 0
    assert result["prepare"]["unavailable"] == 1


async def test_prepare_skips_polls_and_locations(db_session, test_user):
    chat = await _chat(db_session, test_user)
    await _message(db_session, chat, 400, media_type="other", media_file_name=None)

    with _roomy_disk(), _enqueue_spy() as enqueue:
        result = await _prepare(db_session, test_user, media_types=["other"])

    enqueue.assert_not_called()
    assert result["prepare"]["enqueued"] == 0


async def test_prepare_stops_at_the_per_call_cap(db_session, test_user):
    from app.services.file_browse_service import MAX_PREPARE_PER_CALL

    chat = await _chat(db_session, test_user)
    for index in range(MAX_PREPARE_PER_CALL + 3):
        await _message(db_session, chat, 500 + index)

    with _roomy_disk(), _enqueue_spy() as enqueue:
        result = await _prepare(db_session, test_user, limit=MAX_PREPARE_PER_CALL + 3)

    assert len(enqueue.call_args.args[0]) == MAX_PREPARE_PER_CALL
    assert result["prepare"]["skipped_over_cap"] == 3
    assert "still waiting" in result["next_action"]


async def test_prepare_refuses_the_whole_batch_when_the_volume_would_fill(
    db_session, test_user
):
    """A partial batch would leave half the files terminally DISK_FULL."""
    chat = await _chat(db_session, test_user)
    for index in range(3):
        await _message(db_session, chat, 600 + index, media_file_size=10**9)

    with (
        patch(
            "app.services.tool_registry.shutil.disk_usage",
            return_value=SimpleNamespace(total=0, used=0, free=1024),
        ),
        _enqueue_spy() as enqueue,
    ):
        result = await _prepare(db_session, test_user)

    enqueue.assert_not_called()
    assert result["prepare"]["error_code"] == "insufficient_disk"
    assert len(result["files"]) == 3, "the listing survives a refused batch"
    assert "free space" in result["next_action"]


async def test_prepare_refuses_to_add_work_when_too_much_is_already_in_flight(
    db_session, test_user
):
    from app.services.file_browse_service import MAX_IN_FLIGHT_MESSAGES

    chat = await _chat(db_session, test_user)
    for index in range(MAX_IN_FLIGHT_MESSAGES):
        await _message(
            db_session,
            chat,
            700 + index,
            media_processing_status=MediaProcessingStatus.QUEUED,
        )
    await _message(db_session, chat, 9000)

    with _roomy_disk(), _enqueue_spy() as enqueue:
        result = await _prepare(db_session, test_user, file_name="f9000")

    enqueue.assert_not_called()
    assert result["prepare"]["error_code"] == "too_many_in_flight"


async def test_a_deep_pending_backlog_does_not_block_new_work(db_session, test_user):
    """PENDING is the metered backlog, not a dispatch claim.

    Production carries ~900 PENDING rows as its steady state, so counting them
    against the ceiling meant prepare=true could never start anything at all.
    """
    from app.services.file_browse_service import MAX_IN_FLIGHT_MESSAGES

    chat = await _chat(db_session, test_user)
    for index in range(MAX_IN_FLIGHT_MESSAGES * 2):
        await _message(
            db_session,
            chat,
            1100 + index,
            media_processing_status=MediaProcessingStatus.PENDING,
        )
    await _message(db_session, chat, 9100)

    with _roomy_disk(), _enqueue_spy() as enqueue:
        result = await _prepare(db_session, test_user, file_name="f9100")

    assert result["prepare"]["error_code"] is None
    assert result["prepare"]["enqueued"] == 1
    enqueue.assert_called_once()


async def test_polling_the_same_arguments_enqueues_nothing_twice(db_session, test_user):
    """The polling contract is re-sending identical arguments; it must be cheap."""
    chat = await _chat(db_session, test_user)
    await _message(db_session, chat, 800)

    with _roomy_disk(), _enqueue_spy() as enqueue:
        await _prepare(db_session, test_user)
        first = enqueue.call_count
        result = await _prepare(db_session, test_user)

    assert first == 1
    assert enqueue.call_count == 1
    assert result["prepare"]["enqueued"] == 0
    assert result["prepare"]["already_in_progress"] == 1


async def test_prepare_reports_the_deferred_pipeline_without_losing_the_listing(
    db_session, test_user
):
    chat = await _chat(db_session, test_user)
    await _message(db_session, chat, 900)

    with (
        patch(
            "app.services.tool_registry.settings.media_pipeline_enabled",
            False,
        ),
        _enqueue_spy() as enqueue,
    ):
        result = await _prepare(db_session, test_user)

    enqueue.assert_not_called()
    assert result["prepare"]["error_code"] == "media_pipeline_deferred"
    assert len(result["files"]) == 1


async def test_prepare_works_from_an_exact_set_of_locators(db_session, test_user):
    """The path from search_messages: it hands back locators, not filters."""
    chat = await _chat(db_session, test_user)
    wanted = await _message(db_session, chat, 1000)
    await _message(db_session, chat, 1001)

    with _roomy_disk(), _enqueue_spy() as enqueue:
        result = await _prepare(
            db_session,
            test_user,
            files=[{"chat_id": str(chat.id), "telegram_message_id": 1000}],
        )

    assert enqueue.call_args.args[0] == [wanted.id]
    assert len(result["files"]) == 1


@pytest.mark.parametrize("scope", ["read", "write"])
async def test_a_read_key_can_stage_a_page_of_files(db_session, test_user, scope):
    """Filling our own cache is a read, like sync - it posts nothing to Telegram."""
    from app.services.tool_registry import required_scope

    assert required_scope("get_files") is None
