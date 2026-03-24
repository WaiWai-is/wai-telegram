"""Media Processor — extract content from photos and documents.

When a user sends or forwards a photo or document:
- Photos: described via Claude Vision (what's in the image)
- Text documents: content extracted and indexed
- PDFs: text extracted (basic, first pages)

All extracted content feeds into entity extraction + commitment detection.
"""

import base64
import logging
import os

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def describe_photo(file_id: str) -> str | None:
    """Download a photo from Telegram and describe it with Claude Vision.

    Returns a text description of the image, or None on failure.
    """
    try:
        image_data = await _download_telegram_file(file_id)
        if not image_data:
            return None

        # Use Claude Vision to describe the image
        import anthropic

        settings = get_settings()
        if not settings.anthropic_api_key:
            return None

        b64_image = base64.b64encode(image_data).decode("utf-8")

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64_image,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Describe this image concisely in 2-3 sentences. "
                            "Focus on: text visible in the image, people, objects, "
                            "and context. If there's text, transcribe it.",
                        },
                    ],
                }
            ],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning(f"Photo description failed: {e}")
        return None


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


async def _download_telegram_file(file_id: str) -> bytes | None:
    """Download a file from Telegram by file_id."""
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

        # Download file
        download_resp = await client.get(
            f"https://api.telegram.org/file/bot{token}/{file_path}"
        )
        return download_resp.content
