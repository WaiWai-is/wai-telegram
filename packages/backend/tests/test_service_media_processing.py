from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.models.chat import TelegramChat
from app.models.message import MediaProcessingStatus, TelegramMessage
from app.services.media_processing_service import (
    ClaimedMediaMessage,
    claim_media_message,
    process_local_media,
    summarize_existing_transcript,
)


async def test_claim_is_atomic_and_prevents_duplicate_billable_work(
    db_session,
    test_user,
):
    chat = TelegramChat(
        user_id=test_user.id,
        telegram_chat_id=123,
        chat_type="private",
        title="Media",
    )
    db_session.add(chat)
    await db_session.flush()
    message = TelegramMessage(
        chat_id=chat.id,
        telegram_message_id=456,
        text="caption",
        has_media=True,
        media_type="audio",
        media_processing_status=MediaProcessingStatus.PENDING,
        sent_at=chat.created_at,
    )
    db_session.add(message)
    await db_session.flush()

    claimed = await claim_media_message(db_session, message.id)
    duplicate = await claim_media_message(db_session, message.id)

    assert claimed is not None
    assert claimed.user_id == test_user.id
    assert claimed.telegram_message_id == 456
    assert duplicate is None
    assert message.media_processing_status == MediaProcessingStatus.PROCESSING
    assert message.media_processing_attempts == 1


async def test_audio_is_transcribed_once_then_summarized(tmp_path):
    source = tmp_path / "voice.ogg"
    source.write_bytes(b"audio")

    with (
        patch(
            "app.services.media_processing_service.transcribe_media_file",
            new_callable=AsyncMock,
            return_value="Полная расшифровка.",
        ) as transcribe,
        patch(
            "app.services.media_processing_service.summarize_text",
            new_callable=AsyncMock,
            return_value="Короткое резюме.",
        ) as summarize,
    ):
        result = await process_local_media(source, "audio", "audio/ogg")

    assert result.content_text == "Полная расшифровка."
    assert result.content_summary == "Короткое резюме."
    assert result.content_model == "deepgram:nova-3"
    transcribe.assert_awaited_once_with(source, "audio/ogg")
    summarize.assert_awaited_once_with("Полная расшифровка.")


async def test_video_extracts_compact_audio_before_transcription(tmp_path):
    source = tmp_path / "meeting.mp4"
    source.write_bytes(b"video")
    extracted = tmp_path / "meeting.ogg"

    with (
        patch(
            "app.services.media_processing_service.extract_video_audio",
            new_callable=AsyncMock,
            return_value=extracted,
        ) as extract,
        patch(
            "app.services.media_processing_service.transcribe_media_file",
            new_callable=AsyncMock,
            return_value="Transcript",
        ) as transcribe,
        patch(
            "app.services.media_processing_service.summarize_text",
            new_callable=AsyncMock,
            return_value="Summary",
        ),
    ):
        await process_local_media(source, "video", "video/mp4")

    extract.assert_awaited_once_with(source)
    transcribe.assert_awaited_once_with(extracted, "audio/ogg")


async def test_long_audio_is_chunked_to_avoid_provider_request_timeout(tmp_path):
    source = tmp_path / "meeting.m4a"
    source.write_bytes(b"audio")
    chunks = [tmp_path / "chunk-0000.ogg", tmp_path / "chunk-0001.ogg"]

    with (
        patch(
            "app.services.media_processing_service.split_audio_for_transcription",
            new_callable=AsyncMock,
            return_value=chunks,
        ) as split,
        patch(
            "app.services.media_processing_service.transcribe_media_file",
            new_callable=AsyncMock,
            side_effect=["Первая часть.", "Вторая часть."],
        ) as transcribe,
        patch(
            "app.services.media_processing_service.summarize_text",
            new_callable=AsyncMock,
            return_value="Summary",
        ),
    ):
        result = await process_local_media(
            source,
            "audio",
            "audio/mp4",
            duration_seconds=1_201,
        )

    assert result.content_text == "Первая часть.\n\nВторая часть."
    split.assert_awaited_once_with(source)
    assert transcribe.await_count == 2
    assert all(call.args[1] == "audio/ogg" for call in transcribe.await_args_list)


async def test_document_text_is_extracted_then_summarized(tmp_path):
    source = tmp_path / "brief.pdf"
    source.write_bytes(b"pdf")

    with (
        patch(
            "app.services.media_processing_service.extract_document_text",
            new_callable=AsyncMock,
            return_value="Extracted text",
        ) as extract,
        patch(
            "app.services.media_processing_service.summarize_text",
            new_callable=AsyncMock,
            return_value="Summary",
        ),
    ):
        result = await process_local_media(source, "document", "application/pdf")

    assert result.content_text == "Extracted text"
    assert result.content_summary == "Summary"
    assert result.content_model == "markitdown:0.1.6"
    extract.assert_awaited_once_with(source)


async def test_photo_uses_single_vision_call_without_second_summary(tmp_path):
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"jpeg")

    analysis = type(
        "Analysis",
        (),
        {"visible_text": "Встреча 10:00", "summary": "Фото расписания."},
    )()
    with (
        patch(
            "app.services.media_processing_service.analyze_image",
            new_callable=AsyncMock,
            return_value=analysis,
        ) as analyze,
        patch(
            "app.services.media_processing_service.summarize_text",
            new_callable=AsyncMock,
        ) as summarize,
    ):
        result = await process_local_media(source, "photo", "image/jpeg")

    assert result.content_text == "Встреча 10:00"
    assert result.content_summary == "Фото расписания."
    assert result.content_model == "gpt-5.6-luna"
    analyze.assert_awaited_once_with(source, "image/jpeg")
    summarize.assert_not_awaited()


async def test_legacy_transcript_is_summarized_without_buying_transcription_again():
    job = ClaimedMediaMessage(
        id=uuid4(),
        user_id=uuid4(),
        chat_id=uuid4(),
        telegram_message_id=1,
        caption=None,
        media_type="voice",
        file_name="voice.ogg",
        mime_type="audio/ogg",
        file_size=123,
        duration_seconds=5,
        existing_content_text="Уже готовая расшифровка.",
        transcribed_at=datetime.now(UTC),
    )

    with (
        patch(
            "app.services.media_processing_service.summarize_text",
            new_callable=AsyncMock,
            return_value="Резюме.",
        ),
        patch(
            "app.services.media_processing_service.transcribe_media_file",
            new_callable=AsyncMock,
        ) as transcribe,
    ):
        reused = await summarize_existing_transcript(job)

    assert reused is not None
    content, info = reused
    assert content.content_text == "Уже готовая расшифровка."
    assert content.content_summary == "Резюме."
    assert info.file_name == "voice.ogg"
    transcribe.assert_not_awaited()
