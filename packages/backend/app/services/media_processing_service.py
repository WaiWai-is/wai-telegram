import asyncio
import logging
import mimetypes
import re
import shutil
import tempfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.errors import FloodWaitError

from app.core.config import get_settings
from app.core.database import get_db_context
from app.models.chat import TelegramChat
from app.models.message import (
    MediaProcessingStatus,
    MessageContentChunk,
    TelegramMessage,
)
from app.services.embedding_service import (
    PreparedMediaContentIndex,
    prepare_media_content_index,
)
from app.services.media_content_service import (
    IMAGE_MEDIA_TYPES,
    MEDIA_TRANSCRIPTION_TYPES,
    MediaDocumentExtractionError,
    MediaInfo,
    MediaProcessingConfigurationError,
    MediaProcessingError,
    MediaProviderRequestError,
    MediaProviderResponseError,
    analyze_image,
    extract_document_text,
    get_media_info,
    summarize_text,
    transcribe_media_file,
)
from app.services.messaging_service import _resolve_chat_entity
from app.services.telegram_client import (
    TelegramSessionUnauthorizedError,
    get_client,
)

logger = logging.getLogger(__name__)
settings = get_settings()
_media_clients: dict[UUID, TelegramClient] = {}


class MediaDownloadError(MediaProcessingError):
    """Telegram did not provide the expected media file."""


class MediaConversionError(MediaProcessingError):
    """A video audio track could not be converted for transcription."""


class MediaIndexingError(MediaProcessingError):
    """Search embeddings could not be prepared completely."""


async def _get_media_client(user_id: UUID, db: AsyncSession) -> TelegramClient:
    """Reuse one Telethon client per user inside a persistent worker process."""
    cached = _media_clients.get(user_id)
    if cached is not None:
        if cached.is_connected():
            return cached
        _media_clients.pop(user_id, None)
        await cached.disconnect()

    client = await get_client(user_id, db)
    _media_clients[user_id] = client
    return client


async def _discard_media_client(user_id: UUID, expected_client: TelegramClient) -> None:
    """Remove and close a client after a network or authorization failure."""
    if _media_clients.get(user_id) is expected_client:
        _media_clients.pop(user_id, None)
    await expected_client.disconnect()


async def disconnect_media_clients() -> None:
    """Close all worker-local Telethon clients before process shutdown."""
    clients = list(_media_clients.values())
    _media_clients.clear()
    await asyncio.gather(*(client.disconnect() for client in clients))


@dataclass(frozen=True)
class ClaimedMediaMessage:
    id: UUID
    user_id: UUID
    chat_id: UUID
    telegram_message_id: int
    caption: str | None
    media_type: str
    file_name: str | None
    mime_type: str | None
    file_size: int | None
    duration_seconds: int | None
    existing_content_text: str | None
    transcribed_at: datetime | None
    legacy_transcript_in_text: bool = False


@dataclass(frozen=True)
class ProcessedMediaContent:
    content_text: str | None
    content_summary: str
    content_model: str
    summary_model: str
    transcribed: bool


async def claim_media_message(
    db: AsyncSession,
    message_id: UUID,
) -> ClaimedMediaMessage | None:
    """Atomically claim pending media so duplicate tasks cannot spend twice."""
    claimed_id = (
        await db.execute(
            update(TelegramMessage)
            .where(
                TelegramMessage.id == message_id,
                TelegramMessage.has_media.is_(True),
                TelegramMessage.media_processing_status.in_(
                    (
                        MediaProcessingStatus.PENDING,
                        MediaProcessingStatus.QUEUED,
                    )
                ),
            )
            .values(
                media_processing_status=MediaProcessingStatus.PROCESSING,
                media_processing_attempts=TelegramMessage.media_processing_attempts + 1,
                media_processing_started_at=datetime.now(UTC),
                media_processing_error_code=None,
                media_processing_error=None,
            )
            .returning(TelegramMessage.id)
        )
    ).scalar_one_or_none()
    if claimed_id is None:
        return None

    row = (
        await db.execute(
            select(
                TelegramMessage.id,
                TelegramChat.user_id,
                TelegramMessage.chat_id,
                TelegramMessage.telegram_message_id,
                TelegramMessage.text,
                TelegramMessage.media_type,
                TelegramMessage.media_file_name,
                TelegramMessage.media_mime_type,
                TelegramMessage.media_file_size,
                TelegramMessage.media_duration_seconds,
                TelegramMessage.content_text,
                TelegramMessage.transcribed_at,
            )
            .join(TelegramChat, TelegramChat.id == TelegramMessage.chat_id)
            .where(TelegramMessage.id == claimed_id)
        )
    ).one()
    legacy_transcript_in_text = bool(
        row.transcribed_at is not None
        and row.content_text is None
        and row.text
        and row.media_type in MEDIA_TRANSCRIPTION_TYPES
    )
    return ClaimedMediaMessage(
        id=row.id,
        user_id=row.user_id,
        chat_id=row.chat_id,
        telegram_message_id=row.telegram_message_id,
        caption=None if legacy_transcript_in_text else row.text,
        media_type=row.media_type or "other",
        file_name=row.media_file_name,
        mime_type=row.media_mime_type,
        file_size=row.media_file_size,
        duration_seconds=row.media_duration_seconds,
        existing_content_text=(
            row.text if legacy_transcript_in_text else row.content_text
        ),
        transcribed_at=row.transcribed_at,
        legacy_transcript_in_text=legacy_transcript_in_text,
    )


async def extract_video_audio(source: Path) -> Path:
    """Extract a small mono Opus stream so large videos do not waste bandwidth."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise MediaProcessingConfigurationError("ffmpeg is required for video")

    output = source.with_name(f"{source.stem}.audio.ogg")
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "libopus",
        "-b:a",
        "32k",
        "-y",
        str(output),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        detail = stderr.decode("utf-8", errors="replace").strip()[:300]
        suffix = f": {detail}" if detail else ""
        raise MediaConversionError(f"Video has no usable audio track{suffix}")
    return output


async def split_audio_for_transcription(source: Path) -> list[Path]:
    """Normalize and split long media into bounded Nova-3 batch requests."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise MediaProcessingConfigurationError(
            "ffmpeg is required for long audio and video"
        )

    pattern = source.with_name("chunk-%04d.ogg")
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "libopus",
        "-b:a",
        "32k",
        "-f",
        "segment",
        "-segment_time",
        str(settings.media_transcription_chunk_seconds),
        "-reset_timestamps",
        "1",
        "-y",
        str(pattern),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    chunks = sorted(source.parent.glob("chunk-*.ogg"))
    if (
        process.returncode != 0
        or not chunks
        or any(chunk.stat().st_size == 0 for chunk in chunks)
    ):
        detail = stderr.decode("utf-8", errors="replace").strip()[:300]
        suffix = f": {detail}" if detail else ""
        raise MediaConversionError(f"Could not split media audio{suffix}")
    return chunks


async def process_local_media(
    path: Path,
    media_type: str,
    mime_type: str | None,
    duration_seconds: int | None = None,
) -> ProcessedMediaContent:
    """Produce full searchable content plus one concise summary."""
    if media_type in IMAGE_MEDIA_TYPES:
        analysis = await analyze_image(path, mime_type)
        return ProcessedMediaContent(
            content_text=analysis.visible_text or None,
            content_summary=analysis.summary,
            content_model=settings.media_summary_model,
            summary_model=settings.media_summary_model,
            transcribed=False,
        )

    if media_type in MEDIA_TRANSCRIPTION_TYPES:
        if (
            duration_seconds is not None
            and duration_seconds > settings.media_transcription_chunk_seconds
        ):
            transcription_paths = await split_audio_for_transcription(path)
            transcription_mime_type = "audio/ogg"
        elif media_type in {"video", "video_note"}:
            transcription_paths = [await extract_video_audio(path)]
            transcription_mime_type = "audio/ogg"
        else:
            transcription_paths = [path]
            transcription_mime_type = mime_type
        transcript_parts = [
            await transcribe_media_file(
                transcription_path,
                transcription_mime_type,
            )
            for transcription_path in transcription_paths
        ]
        transcript = "\n\n".join(transcript_parts)
        return ProcessedMediaContent(
            content_text=transcript,
            content_summary=await summarize_text(transcript),
            content_model=f"deepgram:{settings.deepgram_model}",
            summary_model=settings.media_summary_model,
            transcribed=True,
        )

    extracted_text = await extract_document_text(path)
    return ProcessedMediaContent(
        content_text=extracted_text,
        content_summary=await summarize_text(extracted_text),
        content_model="markitdown:0.1.6",
        summary_model=settings.media_summary_model,
        transcribed=False,
    )


async def summarize_existing_transcript(
    job: ClaimedMediaMessage,
) -> tuple[ProcessedMediaContent, MediaInfo] | None:
    """Reuse legacy transcripts so migration does not buy them a second time."""
    transcript = (job.existing_content_text or "").strip()
    if (
        not transcript
        or job.transcribed_at is None
        or job.media_type not in MEDIA_TRANSCRIPTION_TYPES
    ):
        return None
    return (
        ProcessedMediaContent(
            content_text=transcript,
            content_summary=await summarize_text(transcript),
            content_model=f"deepgram:{settings.deepgram_model}",
            summary_model=settings.media_summary_model,
            transcribed=True,
        ),
        MediaInfo(
            media_type=job.media_type,
            file_name=job.file_name,
            mime_type=job.mime_type,
            file_size=job.file_size,
            duration_seconds=job.duration_seconds,
        ),
    )


def _safe_suffix(file_name: str | None, mime_type: str | None) -> str:
    suffix = Path(file_name).suffix if file_name else ""
    if not suffix and mime_type:
        suffix = mimetypes.guess_extension(mime_type) or ""
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,10}", suffix):
        return ".bin"
    return suffix.lower()


async def _download_telegram_media(
    job: ClaimedMediaMessage,
    directory: Path,
) -> tuple[Path, MediaInfo]:
    client = None
    try:
        timeout_seconds = settings.media_download_timeout_seconds
        async with asyncio.timeout(timeout_seconds):
            async with get_db_context() as db:
                chat = (
                    await db.execute(
                        select(TelegramChat).where(
                            TelegramChat.id == job.chat_id,
                            TelegramChat.user_id == job.user_id,
                        )
                    )
                ).scalar_one_or_none()
                if chat is None:
                    raise MediaDownloadError("Chat is no longer available")
                client = await _get_media_client(job.user_id, db)
                peer = await _resolve_chat_entity(client, db, chat)

            telegram_message = await client.get_messages(
                peer,
                ids=job.telegram_message_id,
            )
            info = get_media_info(telegram_message)
            if info is None:
                raise MediaDownloadError("Telegram message has no downloadable media")

            destination = directory / (
                "source" + _safe_suffix(info.file_name or job.file_name, info.mime_type)
            )
            downloaded = await client.download_media(
                telegram_message,
                file=str(destination),
            )
            downloaded_path = Path(downloaded) if downloaded else destination
            if not downloaded_path.is_file() or downloaded_path.stat().st_size == 0:
                raise MediaDownloadError("Telegram media download returned no file")
            if info.file_size is None:
                info = replace(info, file_size=downloaded_path.stat().st_size)
            return downloaded_path, info
    except TimeoutError as exc:
        if client is not None:
            await _discard_media_client(job.user_id, client)
        raise MediaDownloadError(
            f"Telegram media download timed out after {timeout_seconds:g} seconds"
        ) from exc
    except TelegramSessionUnauthorizedError:
        if client is not None:
            await _discard_media_client(job.user_id, client)
        raise
    except FloodWaitError as exc:
        # A server-side throttle does not mean the persistent connection is
        # broken. Disconnecting here churns exported media-DC senders and can
        # amplify the flood wait for the remaining backlog.
        raise MediaDownloadError(
            f"Telegram media download failed (FloodWaitError: {exc.seconds}s)"
        ) from exc
    except MediaProcessingError:
        raise
    except Exception as exc:
        if client is not None:
            await _discard_media_client(job.user_id, client)
        raise MediaDownloadError(
            f"Telegram media download failed ({type(exc).__name__})"
        ) from exc


def _error_details(error: Exception) -> tuple[str, str]:
    if isinstance(error, TelegramSessionUnauthorizedError):
        return "telegram_session_unauthorized", "Reconnect Telegram and try again"
    if isinstance(error, MediaProcessingConfigurationError):
        return "configuration_error", str(error)
    if isinstance(error, MediaDownloadError):
        return "download_error", str(error)
    if isinstance(error, MediaConversionError):
        return "conversion_error", str(error)
    if isinstance(error, MediaDocumentExtractionError):
        return "document_extraction_error", str(error)
    if isinstance(error, MediaProviderRequestError):
        return "provider_request_error", str(error)
    if isinstance(error, MediaProviderResponseError):
        return "provider_response_error", str(error)
    if isinstance(error, MediaIndexingError):
        return "indexing_error", str(error)
    if isinstance(error, MediaProcessingError):
        return "processing_error", str(error)
    return "unexpected_error", f"Unexpected {type(error).__name__}"


async def _mark_failed(message_id: UUID, error: Exception) -> None:
    code, detail = _error_details(error)
    async with get_db_context() as db:
        await db.execute(
            update(TelegramMessage)
            .where(
                TelegramMessage.id == message_id,
                TelegramMessage.media_processing_status
                == MediaProcessingStatus.PROCESSING,
            )
            .values(
                media_processing_status=MediaProcessingStatus.FAILED,
                media_processing_error_code=code,
                media_processing_error=detail,
                media_processed_at=datetime.now(UTC),
            )
        )


async def _finalize_media(
    job: ClaimedMediaMessage,
    info: MediaInfo,
    content: ProcessedMediaContent,
    index: PreparedMediaContentIndex,
) -> None:
    now = datetime.now(UTC)
    async with get_db_context() as db:
        message = (
            await db.execute(
                select(TelegramMessage)
                .where(
                    TelegramMessage.id == job.id,
                    TelegramMessage.media_processing_status
                    == MediaProcessingStatus.PROCESSING,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if message is None:
            raise MediaProcessingError("Media claim is no longer active")

        await db.execute(
            delete(MessageContentChunk).where(
                MessageContentChunk.message_id == message.id
            )
        )
        for chunk_index, chunk in enumerate(index.chunks):
            db.add(
                MessageContentChunk(
                    message_id=message.id,
                    chunk_index=chunk_index,
                    text=chunk.text,
                    embedding=chunk.embedding,
                    embedded_at=now,
                )
            )

        message.media_type = info.media_type
        message.media_file_name = info.file_name or job.file_name
        message.media_mime_type = info.mime_type or job.mime_type
        message.media_file_size = info.file_size
        message.media_duration_seconds = info.duration_seconds
        message.content_text = content.content_text
        if job.legacy_transcript_in_text:
            message.text = None
        message.content_summary = content.content_summary
        message.content_model = content.content_model
        message.summary_model = content.summary_model
        message.embedding = index.message_embedding
        message.embedded_at = now
        message.transcribed_at = now if content.transcribed else None
        message.media_processing_status = MediaProcessingStatus.READY
        message.media_processing_error_code = None
        message.media_processing_error = None
        message.media_processed_at = now


async def process_media_message(message_id: UUID) -> str:
    """Run one idempotent background media job without automatic retries."""
    async with get_db_context() as db:
        job = await claim_media_message(db, message_id)
    if job is None:
        return "skipped"

    try:
        reused = await summarize_existing_transcript(job)
        if reused is not None:
            content, info = reused
        else:
            with tempfile.TemporaryDirectory(prefix="wai-media-") as temp_dir:
                source, info = await _download_telegram_media(job, Path(temp_dir))
                content = await process_local_media(
                    source,
                    info.media_type,
                    info.mime_type,
                    info.duration_seconds,
                )
        try:
            index = await prepare_media_content_index(
                caption=job.caption,
                summary=content.content_summary,
                content_text=content.content_text,
            )
        except Exception as exc:
            raise MediaIndexingError(
                f"Search indexing failed ({type(exc).__name__})"
            ) from exc
        await _finalize_media(job, info, content, index)
        return "ready"
    except Exception as exc:
        await _mark_failed(job.id, exc)
        code, _ = _error_details(exc)
        logger.error(
            "Media processing failed for message %s with code %s",
            job.id,
            code,
        )
        return "failed"
