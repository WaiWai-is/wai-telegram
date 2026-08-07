from datetime import UTC, datetime

from app.models.chat import ChatType, TelegramChat
from app.models.media import (
    MediaObject,
    MediaObjectStatus,
    MediaStage,
    TranscriptSegment,
)
from app.models.message import MessageRevision, TelegramMessage


async def test_media_cache_and_transcript_checkpoints_persist(db_session, test_user):
    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=9090,
        chat_type=ChatType.PRIVATE,
        title="Media",
    )
    db_session.add(chat)
    await db_session.flush()
    message = TelegramMessage(
        chat_id=chat.id,
        telegram_message_id=42,
        has_media=True,
        media_type="audio",
        sent_at=datetime.now(UTC),
    )
    db_session.add(message)
    await db_session.flush()

    cached = MediaObject(
        user_id=test_user.id,
        message_id=message.id,
        cache_key="a" * 64,
        relative_path="aa/" + "a" * 64 + "/original.mp3",
        stage=MediaStage.EXTRACTION,
        status=MediaObjectStatus.CACHED,
        byte_offset=123,
        sha256="b" * 64,
    )
    segment = TranscriptSegment(
        message_id=message.id,
        sequence=0,
        start_ms=0,
        end_ms=1200,
        speaker="0",
        confidence=0.98,
        language="ru",
        text="Привет",
    )
    revision = MessageRevision(
        message_id=message.id,
        revision=1,
        text="До редактирования",
        edited_at=datetime.now(UTC),
    )
    db_session.add_all([cached, segment, revision])
    await db_session.flush()

    assert cached.byte_offset == 123
    assert cached.status == MediaObjectStatus.CACHED
    assert segment.end_ms == 1200
    assert revision.message_id == message.id
