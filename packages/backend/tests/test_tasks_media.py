from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.models.chat import ChatType, TelegramChat
from app.models.message import MediaProcessingStatus, TelegramMessage
from app.tasks.media_tasks import (
    _find_pending_and_reap_stale,
    enqueue_media_processing,
    process_message_media_task,
)


def test_media_task_has_no_automatic_retry():
    message_id = uuid4()
    awaitable_marker = object()
    with (
        patch(
            "app.tasks.media_tasks.process_media_message",
            new=MagicMock(return_value=awaitable_marker),
        ),
        patch(
            "app.tasks.media_tasks.run_async",
            return_value="failed",
        ) as run,
    ):
        result = process_message_media_task.run(str(message_id))

    assert result == {"message_id": str(message_id), "status": "failed"}
    run.assert_called_once_with(awaitable_marker)
    assert process_message_media_task.max_retries == 0


def test_enqueue_routes_expensive_work_to_dedicated_media_queue():
    message_id = uuid4()
    with patch.object(process_message_media_task, "apply_async") as apply:
        enqueue_media_processing([message_id])

    apply.assert_called_once_with(
        args=[str(message_id)],
        queue="media",
    )


async def test_dispatch_claims_pending_rows_once(db_session, test_user):
    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=321,
        chat_type=ChatType.PRIVATE,
        title="Queue",
    )
    db_session.add(chat)
    await db_session.flush()
    message = TelegramMessage(
        chat_id=chat.id,
        telegram_message_id=654,
        text=None,
        has_media=True,
        media_type="video",
        media_processing_status=MediaProcessingStatus.PENDING,
        sent_at=datetime.now(UTC),
    )
    db_session.add(message)
    await db_session.flush()

    @asynccontextmanager
    async def test_db_context():
        yield db_session

    with (
        patch(
            "app.tasks.media_tasks.get_db_context",
            side_effect=test_db_context,
        ),
        patch("app.tasks.media_tasks.settings") as task_settings,
    ):
        task_settings.media_queue_stale_minutes = 360
        task_settings.media_processing_stale_minutes = 120
        task_settings.media_dispatch_target_depth = 20
        first = await _find_pending_and_reap_stale()
        second = await _find_pending_and_reap_stale()

    assert first == [message.id]
    assert second == []
    assert message.media_processing_status == MediaProcessingStatus.QUEUED


async def test_dispatch_claims_uninitialized_historical_media(
    db_session,
    test_user,
):
    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=322,
        chat_type=ChatType.PRIVATE,
        title="Historical queue",
    )
    db_session.add(chat)
    await db_session.flush()
    message = TelegramMessage(
        chat_id=chat.id,
        telegram_message_id=655,
        text="Старая расшифровка.",
        has_media=True,
        media_type="voice",
        media_processing_status=None,
        transcribed_at=datetime.now(UTC),
        sent_at=datetime.now(UTC),
    )
    db_session.add(message)
    await db_session.flush()

    @asynccontextmanager
    async def test_db_context():
        yield db_session

    with (
        patch(
            "app.tasks.media_tasks.get_db_context",
            side_effect=test_db_context,
        ),
        patch("app.tasks.media_tasks.settings") as task_settings,
    ):
        task_settings.media_queue_stale_minutes = 360
        task_settings.media_processing_stale_minutes = 120
        task_settings.media_dispatch_target_depth = 20
        claimed = await _find_pending_and_reap_stale()

    assert claimed == [message.id]
    assert message.media_processing_status == MediaProcessingStatus.QUEUED


async def test_dispatch_prioritizes_live_pending_media_over_historical_backfill(
    db_session,
    test_user,
):
    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=323,
        chat_type=ChatType.PRIVATE,
        title="Live queue priority",
    )
    db_session.add(chat)
    await db_session.flush()
    now = datetime.now(UTC)
    live_photo = TelegramMessage(
        chat_id=chat.id,
        telegram_message_id=656,
        text=None,
        has_media=True,
        media_type="photo",
        media_processing_status=MediaProcessingStatus.PENDING,
        sent_at=now - timedelta(days=1),
    )
    historical_voice = TelegramMessage(
        chat_id=chat.id,
        telegram_message_id=657,
        text="Старая расшифровка.",
        has_media=True,
        media_type="voice",
        media_processing_status=None,
        transcribed_at=now,
        sent_at=now,
    )
    db_session.add_all([live_photo, historical_voice])
    await db_session.flush()

    @asynccontextmanager
    async def test_db_context():
        yield db_session

    with (
        patch(
            "app.tasks.media_tasks.get_db_context",
            side_effect=test_db_context,
        ),
        patch("app.tasks.media_tasks.settings") as task_settings,
    ):
        task_settings.media_queue_stale_minutes = 360
        task_settings.media_processing_stale_minutes = 120
        task_settings.media_dispatch_target_depth = 1
        claimed = await _find_pending_and_reap_stale()

    assert claimed == [live_photo.id]
    assert live_photo.media_processing_status == MediaProcessingStatus.QUEUED
    assert historical_voice.media_processing_status is None
