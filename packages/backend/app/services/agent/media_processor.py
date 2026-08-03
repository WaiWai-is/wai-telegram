"""Media Processor — extract content from photos and documents.

When a user sends or forwards a photo or document:
- Photos: described by the shared vision-capable generation model
- Text documents: content extracted and indexed
- PDFs: text extracted (basic, first pages)

All extracted content feeds into entity extraction + commitment detection.
"""

import base64
import logging
import os

import httpx

from app.core.config import get_settings
from app.services.generation_service import generate_text

logger = logging.getLogger(__name__)


async def describe_photo(file_id: str) -> str | None:
    """Download a photo from Telegram and describe it with the shared model.

    Returns a text description of the image, or None on failure.
    """
    image_data = await _download_telegram_file(file_id)
    if not image_data:
        return None

    # Detect actual image format from magic bytes
    media_type = "image/jpeg"
    if image_data[:8] == b"\x89PNG\r\n\x1a\n":
        media_type = "image/png"
    elif image_data[:4] == b"RIFF" and image_data[8:12] == b"WEBP":
        media_type = "image/webp"
    elif image_data[:3] == b"GIF":
        media_type = "image/gif"

    b64_image = base64.b64encode(image_data).decode("utf-8")

    return await generate_text(
        [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": f"data:{media_type};base64,{b64_image}",
                        "detail": "low",
                    },
                    {
                        "type": "input_text",
                        "text": "Describe this image concisely in 2-3 sentences. "
                        "Focus on visible text, people, objects, and context. "
                        "If there is text, transcribe it.",
                    },
                ],
            }
        ],
        max_output_tokens=300,
    )


async def extract_document_text(
    file_id: str, file_name: str | None = None
) -> str | None:
    """Download a document from Telegram and extract text content.

    Supports: .txt, .py, .json, .md, .csv, .html, .xml, .log
    Returns extracted text or None.
    """
    try:
        doc_data = await _download_telegram_file(file_id)
        if not doc_data:
            return None

        # Only process text-like files
        text_extensions = {
            ".txt",
            ".py",
            ".json",
            ".md",
            ".csv",
            ".html",
            ".xml",
            ".log",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".cfg",
            ".conf",
            ".js",
            ".ts",
            ".css",
            ".sql",
            ".sh",
            ".env",
        }

        if file_name:
            ext = os.path.splitext(file_name)[1].lower()
            if ext not in text_extensions:
                return f"[Document: {file_name} — binary file, content not extracted]"

        # Try to decode as UTF-8 text
        try:
            text = doc_data.decode("utf-8")
            # Limit to first 5000 chars
            if len(text) > 5000:
                text = text[:5000] + f"\n\n... [truncated, {len(doc_data)} bytes total]"
            return text
        except UnicodeDecodeError:
            return f"[Document: {file_name or 'unknown'} — binary content, cannot extract text]"

    except Exception as e:
        logger.warning(f"Document extraction failed: {e}")
        return None


MAX_DOWNLOAD_SIZE = 20 * 1024 * 1024  # 20MB limit


async def _download_telegram_file(file_id: str) -> bytes | None:
    """Download a file from Telegram by file_id. Max 20MB."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or get_settings().telegram_bot_token
    if not token:
        return None

    async with httpx.AsyncClient(timeout=30) as client:
        # Get file path
        resp = await client.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={"file_id": file_id},
        )
        data = resp.json()
        if not data.get("ok"):
            return None

        file_path = data["result"]["file_path"]

        # Download file with size check
        download_resp = await client.get(
            f"https://api.telegram.org/file/bot{token}/{file_path}"
        )
        if len(download_resp.content) > MAX_DOWNLOAD_SIZE:
            logger.warning(f"File too large: {len(download_resp.content)} bytes")
            return None
        return download_resp.content
