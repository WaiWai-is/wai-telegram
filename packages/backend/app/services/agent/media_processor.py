"""Media Processor — extract content from photos and documents.

When a user sends or forwards a photo or document:
- Photos: described by the shared vision-capable generation model
- Text documents: content extracted and indexed
- PDFs: text extracted (basic, first pages)

All extracted content feeds into entity extraction + commitment detection.
"""

import os
import tempfile
from pathlib import Path

from app.core.config import get_settings
from app.services.media_content_service import (
    analyze_image,
    extract_document_text as extract_local_document,
    transcribe_media_file,
)
from app.services.media_processing_service import (
    ProcessedMediaContent,
    process_local_media,
)
from app.services.telegram_bot_api import get_bot_api_client

settings = get_settings()


def _temporary_bot_directory(prefix: str) -> tempfile.TemporaryDirectory[str]:
    parent: str | None = None
    if settings.environment == "production" and getattr(
        settings, "media_pipeline_enabled", True
    ):
        work_root = settings.media_root / "bot-work"
        work_root.mkdir(parents=True, exist_ok=True)
        parent = str(work_root)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=parent)


async def describe_photo(file_id: str) -> str | None:
    """Download a photo from Telegram and describe it with the shared model.

    Returns a text description of the image, or None on failure.
    """
    with _temporary_bot_directory("wai-bot-photo-") as temp_dir:
        path = await _download_telegram_file(file_id, Path(temp_dir) / "photo.bin")
        analysis = await analyze_image(path, None)
        return "\n\n".join(
            part for part in (analysis.summary, analysis.visible_text) if part
        )


async def extract_document_text(file_id: str, file_name: str | None = None) -> str:
    """Download a document from Telegram and extract text content.

    Supports: .txt, .py, .json, .md, .csv, .html, .xml, .log
    Returns extracted text or None.
    """
    with _temporary_bot_directory("wai-bot-document-") as temp_dir:
        name = os.path.basename(file_name or "document.bin")
        path = await _download_telegram_file(file_id, Path(temp_dir) / name)
        return await extract_local_document(path)


async def process_bot_media(
    file_id: str,
    *,
    media_type: str,
    file_name: str | None,
    mime_type: str | None,
    duration_seconds: int | None,
) -> ProcessedMediaContent:
    """Run direct Bot API media through the same extraction pipeline as MTProto."""
    with _temporary_bot_directory("wai-bot-media-") as temp_dir:
        safe_name = os.path.basename(file_name or f"{media_type}.bin")
        path = await _download_telegram_file(file_id, Path(temp_dir) / safe_name)
        return await process_local_media(
            path,
            media_type,
            mime_type,
            duration_seconds,
        )


async def transcribe_bot_voice(file_id: str) -> str:
    """Stream a Bot API voice file to the media volume and transcribe it."""
    with _temporary_bot_directory("wai-bot-voice-") as temp_dir:
        path = await _download_telegram_file(file_id, Path(temp_dir) / "voice.ogg")
        return await transcribe_media_file(path, "audio/ogg")


async def _download_telegram_file(file_id: str, destination: Path) -> Path:
    """Stream a Bot API file to disk without an application size limit."""
    return await get_bot_api_client().download_file_to(file_id, destination)
