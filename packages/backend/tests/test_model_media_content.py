from datetime import UTC, datetime


async def test_message_keeps_caption_content_and_summary_separate(
    db_session, test_user
):
    from app.models.chat import ChatType, TelegramChat
    from app.models.message import MediaProcessingStatus, TelegramMessage

    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=1001,
        chat_type=ChatType.PRIVATE,
        title="Files",
    )
    db_session.add(chat)
    await db_session.flush()

    message = TelegramMessage(
        chat_id=chat.id,
        telegram_message_id=10,
        text="Исходная подпись",
        has_media=True,
        media_type="video",
        media_file_name="meeting.mp4",
        media_mime_type="video/mp4",
        media_file_size=123456,
        content_text="Полная транскрипция встречи.",
        content_summary="Краткое содержание встречи.",
        media_processing_status=MediaProcessingStatus.READY,
        sent_at=datetime.now(UTC),
    )
    db_session.add(message)
    await db_session.flush()

    assert message.text == "Исходная подпись"
    assert message.content_text == "Полная транскрипция встречи."
    assert message.content_summary == "Краткое содержание встречи."
    assert message.media_processing_status == MediaProcessingStatus.READY


async def test_content_chunks_belong_to_message(db_session, test_user):
    from app.models.chat import ChatType, TelegramChat
    from app.models.message import MessageContentChunk, TelegramMessage

    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=1002,
        chat_type=ChatType.PRIVATE,
        title="Files",
    )
    db_session.add(chat)
    await db_session.flush()
    message = TelegramMessage(
        chat_id=chat.id,
        telegram_message_id=11,
        text=None,
        has_media=True,
        media_type="audio",
        sent_at=datetime.now(UTC),
    )
    db_session.add(message)
    await db_session.flush()

    chunk = MessageContentChunk(
        message_id=message.id,
        chunk_index=0,
        text="Первая часть транскрипта",
    )
    db_session.add(chunk)
    await db_session.flush()

    assert chunk.message_id == message.id
    assert chunk.chunk_index == 0
