"""Pruning cached originals must take the database claim with the file.

Leaving the row behind is what turned a full volume into a listing full of files
that advertise a download link, answer 503 behind it, and refuse to be fetched
again because their status still says ready.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.chat import ChatType, TelegramChat
from app.models.media import MediaObject, MediaObjectStatus, MediaStage
from app.models.message import MediaProcessingStatus, TelegramMessage

NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)


@pytest.fixture
def media_root(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    return root


async def _cached(
    db_session,
    test_user,
    root: Path,
    *,
    telegram_message_id: int,
    fetched_at: datetime | None,
    processing: MediaProcessingStatus = MediaProcessingStatus.READY,
    write_file: bool = True,
):
    chat = (await db_session.execute(select(TelegramChat).limit(1))).scalars().first()
    if chat is None:
        chat = TelegramChat(
            user_id=test_user.id,
            telegram_chat_id=9001,
            chat_type=ChatType.PRIVATE,
            title="Prune chat",
        )
        db_session.add(chat)
        await db_session.flush()

    message = TelegramMessage(
        chat_id=chat.id,
        telegram_message_id=telegram_message_id,
        has_media=True,
        media_type="document",
        media_file_name=f"f{telegram_message_id}.pdf",
        media_processing_status=processing,
        content_text="extracted text stays",
        sender_id=1,
        sender_name="S",
        is_outgoing=False,
        sent_at=NOW,
    )
    db_session.add(message)
    await db_session.flush()

    rel = f"ab/{telegram_message_id}/original.pdf"
    if write_file:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 100)
    media_object = MediaObject(
        user_id=test_user.id,
        message_id=message.id,
        cache_key=uuid4().hex * 2,
        relative_path=rel,
        sha256="c" * 64,
        size_bytes=100,
        status=MediaObjectStatus.READY,
        stage=MediaStage.COMPLETE,
        fetched_at=fetched_at,
    )
    db_session.add(media_object)
    await db_session.flush()
    return message, media_object, rel


async def _prune(db_session, root, **kwargs):
    from app.cli import media_cache_prune

    @asynccontextmanager
    async def ctx():
        yield db_session

    with (
        patch.object(media_cache_prune, "get_db_context", side_effect=ctx),
        patch.object(media_cache_prune, "get_settings") as settings,
    ):
        settings.return_value.media_root = root
        return await media_cache_prune.prune_media_cache(**kwargs)


async def test_a_settled_old_original_loses_both_its_file_and_its_row(
    db_session, test_user, media_root
):
    message, media_object, rel = await _cached(
        db_session,
        test_user,
        media_root,
        telegram_message_id=100,
        fetched_at=NOW - timedelta(days=1),
    )

    with patch("app.cli.media_cache_prune.datetime") as clock:
        clock.now.return_value = NOW
        result = await _prune(db_session, media_root)

    assert result["deleted_files"] == 1
    assert not (media_root / rel).exists()
    assert (
        await db_session.execute(
            select(MediaObject).where(MediaObject.id == media_object.id)
        )
    ).scalar_one_or_none() is None
    kept = (
        await db_session.execute(
            select(TelegramMessage).where(TelegramMessage.id == message.id)
        )
    ).scalar_one()
    assert kept.content_text == "extracted text stays", "text must outlive the bytes"


async def test_a_row_whose_file_is_already_gone_is_cleared(
    db_session, test_user, media_root
):
    """The 13,234-row condition: the file went, the claim stayed."""
    _message, media_object, _rel = await _cached(
        db_session,
        test_user,
        media_root,
        telegram_message_id=200,
        fetched_at=NOW - timedelta(days=1),
        write_file=False,
    )

    with patch("app.cli.media_cache_prune.datetime") as clock:
        clock.now.return_value = NOW
        result = await _prune(db_session, media_root)

    assert result["rows_already_missing_a_file"] == 1
    assert (
        await db_session.execute(
            select(MediaObject).where(MediaObject.id == media_object.id)
        )
    ).scalar_one_or_none() is None


async def test_a_recently_fetched_original_is_kept(db_session, test_user, media_root):
    """A caller holding a fresh download link must still find the file there."""
    _m, media_object, rel = await _cached(
        db_session,
        test_user,
        media_root,
        telegram_message_id=300,
        fetched_at=NOW - timedelta(minutes=5),
    )

    with patch("app.cli.media_cache_prune.datetime") as clock:
        clock.now.return_value = NOW
        result = await _prune(db_session, media_root)

    assert result["deleted_files"] == 0
    assert (media_root / rel).exists()
    assert (
        await db_session.execute(
            select(MediaObject).where(MediaObject.id == media_object.id)
        )
    ).scalar_one_or_none() is not None


@pytest.mark.parametrize(
    "processing",
    [MediaProcessingStatus.PENDING, MediaProcessingStatus.PROCESSING],
)
async def test_an_unsettled_file_keeps_its_bytes(
    db_session, test_user, media_root, processing
):
    """Text is not stored yet, so removing the original would lose it for good."""
    _m, _o, rel = await _cached(
        db_session,
        test_user,
        media_root,
        telegram_message_id=400,
        fetched_at=NOW - timedelta(days=1),
        processing=processing,
    )

    with patch("app.cli.media_cache_prune.datetime") as clock:
        clock.now.return_value = NOW
        result = await _prune(db_session, media_root)

    assert result["deleted_files"] == 0
    assert (media_root / rel).exists()


async def test_a_pruned_file_reads_as_not_prepared_and_can_be_fetched_again(
    db_session, test_user, media_root
):
    """The whole point: pruning must reopen the file, not bury it."""
    from app.services.tool_registry import execute_data_tool

    message, _o, _rel = await _cached(
        db_session,
        test_user,
        media_root,
        telegram_message_id=500,
        fetched_at=NOW - timedelta(days=1),
    )
    before = await execute_data_tool(db_session, test_user.id, "get_files", {})
    assert before["files"][0]["download_state"] == "ready"

    with patch("app.cli.media_cache_prune.datetime") as clock:
        clock.now.return_value = NOW
        await _prune(db_session, media_root)

    after = await execute_data_tool(db_session, test_user.id, "get_files", {})
    entry = after["files"][0]
    assert entry["download_state"] == "not_prepared"
    assert entry["media_download_url"] is None
    assert entry["next_action"] == (
        "Call get_files again with prepare=true to fetch this file."
    )

    with (
        patch(
            "app.services.tool_registry.shutil.disk_usage",
        ) as disk,
        patch("app.tasks.media_tasks.enqueue_media_processing") as enqueue,
    ):
        disk.return_value.free = 500 * 1024**3
        staged = await execute_data_tool(
            db_session,
            test_user.id,
            "get_files",
            {
                "files": [
                    {
                        "chat_id": str(message.chat_id),
                        "telegram_message_id": 500,
                    }
                ],
                "prepare": True,
            },
        )

    assert staged["prepare"]["enqueued"] == 1, "a pruned file must be refetchable"
    enqueue.assert_called_once()
