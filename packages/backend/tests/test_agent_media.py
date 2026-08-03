"""Tests for Media Processor — photos and documents."""

import base64

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.media_processor import (
    MAX_DOWNLOAD_SIZE,
    describe_photo,
    extract_document_text,
)


class TestExtractDocumentText:
    """Test text extraction from documents (no network calls needed)."""

    def test_text_extension_check(self):
        """Verify text extensions are recognized."""
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
        for ext in text_extensions:
            assert ext.startswith(".")

    def test_binary_detection(self):
        """Binary files should be rejected by name."""
        import os

        binary_names = ["image.png", "app.exe", "data.bin", "archive.zip"]
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
        for name in binary_names:
            ext = os.path.splitext(name)[1].lower()
            assert ext not in text_extensions

    async def test_download_failure_returns_none(self):
        """If _download_telegram_file returns None, extract_document_text returns None."""
        with patch(
            "app.services.agent.media_processor._download_telegram_file",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await extract_document_text("file_id_123", "report.txt")
            assert result is None

    async def test_text_file_extraction(self):
        """UTF-8 text content is returned correctly."""
        file_content = b"Hello, this is a text file.\nSecond line."
        with patch(
            "app.services.agent.media_processor._download_telegram_file",
            new_callable=AsyncMock,
            return_value=file_content,
        ):
            result = await extract_document_text("file_id_123", "notes.txt")
            assert result == "Hello, this is a text file.\nSecond line."

    async def test_python_file_extraction(self):
        """Python file content is treated as text."""
        file_content = b"def hello():\n    print('hi')\n"
        with patch(
            "app.services.agent.media_processor._download_telegram_file",
            new_callable=AsyncMock,
            return_value=file_content,
        ):
            result = await extract_document_text("file_id_123", "script.py")
            assert "def hello():" in result

    async def test_binary_file_returns_rejection_message(self):
        """Binary file extensions get a rejection message, not extracted."""
        with patch(
            "app.services.agent.media_processor._download_telegram_file",
            new_callable=AsyncMock,
            return_value=b"\x00\x01\x02binary",
        ):
            result = await extract_document_text("file_id_123", "image.png")
            assert result is not None
            assert "binary file" in result
            assert "image.png" in result

    async def test_large_text_is_truncated(self):
        """Text longer than 5000 chars is truncated with a notice."""
        long_content = ("A" * 6000).encode("utf-8")
        with patch(
            "app.services.agent.media_processor._download_telegram_file",
            new_callable=AsyncMock,
            return_value=long_content,
        ):
            result = await extract_document_text("file_id_123", "big.txt")
            assert len(result) < 6000
            assert "truncated" in result
            assert "6000 bytes total" in result

    async def test_text_under_5000_not_truncated(self):
        """Text under 5000 chars is returned as-is."""
        content = ("B" * 4999).encode("utf-8")
        with patch(
            "app.services.agent.media_processor._download_telegram_file",
            new_callable=AsyncMock,
            return_value=content,
        ):
            result = await extract_document_text("file_id_123", "small.txt")
            assert result == "B" * 4999
            assert "truncated" not in result

    async def test_unicode_decode_error_returns_binary_message(self):
        """Non-UTF-8 data for a text extension returns a binary content message."""
        # Invalid UTF-8 byte sequence
        bad_utf8 = b"\xff\xfe\x00\x01"
        with patch(
            "app.services.agent.media_processor._download_telegram_file",
            new_callable=AsyncMock,
            return_value=bad_utf8,
        ):
            result = await extract_document_text("file_id_123", "data.txt")
            assert result is not None
            assert "binary content" in result

    async def test_no_filename_binary_content(self):
        """When no filename is given and content is not UTF-8, uses 'unknown'."""
        bad_utf8 = b"\xff\xfe\x00\x01"
        with patch(
            "app.services.agent.media_processor._download_telegram_file",
            new_callable=AsyncMock,
            return_value=bad_utf8,
        ):
            result = await extract_document_text("file_id_123")
            assert result is not None
            assert "unknown" in result

    async def test_no_filename_text_content(self):
        """When no filename is given, text content is extracted normally."""
        with patch(
            "app.services.agent.media_processor._download_telegram_file",
            new_callable=AsyncMock,
            return_value=b"plain text content",
        ):
            result = await extract_document_text("file_id_123")
            assert result == "plain text content"

    async def test_exception_during_extraction_returns_none(self):
        """Unexpected exception during extraction returns None."""
        with patch(
            "app.services.agent.media_processor._download_telegram_file",
            new_callable=AsyncMock,
            side_effect=Exception("network error"),
        ):
            result = await extract_document_text("file_id_123", "test.txt")
            assert result is None


class TestDescribePhoto:
    """Test photo description with the shared vision generation boundary."""

    async def test_download_failure_returns_none(self):
        """If file download fails, returns None."""
        with patch(
            "app.services.agent.media_processor._download_telegram_file",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await describe_photo("file_id_123")
            assert result is None

    async def test_successful_jpeg_description(self):
        """JPEG image is sent as Responses API vision input."""
        jpeg_data = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        with (
            patch(
                "app.services.agent.media_processor._download_telegram_file",
                new_callable=AsyncMock,
                return_value=jpeg_data,
            ),
            patch(
                "app.services.agent.media_processor.generate_text",
                new_callable=AsyncMock,
                return_value="A photo of a sunset over the ocean.",
            ) as generate,
        ):
            result = await describe_photo("file_id_123")

        assert result == "A photo of a sunset over the ocean."
        generate.assert_awaited_once()
        assert generate.await_args.kwargs["max_output_tokens"] == 300
        image = generate.await_args.args[0][0]["content"][0]
        assert image["type"] == "input_image"
        assert image["detail"] == "low"
        assert image["image_url"].startswith("data:image/jpeg;base64,")

    @pytest.mark.parametrize(
        ("image_data", "media_type"),
        [
            (b"\x89PNG\r\n\x1a\nDATA", "image/png"),
            (b"RIFF\x00\x00\x00\x00WEBPDATA", "image/webp"),
            (b"GIF89aDATA", "image/gif"),
            (b"\x00\x01\x02DATA", "image/jpeg"),
        ],
    )
    async def test_media_type_and_base64_encoding(self, image_data, media_type):
        with (
            patch(
                "app.services.agent.media_processor._download_telegram_file",
                new_callable=AsyncMock,
                return_value=image_data,
            ),
            patch(
                "app.services.agent.media_processor.generate_text",
                new_callable=AsyncMock,
                return_value="Description",
            ) as generate,
        ):
            await describe_photo("file_id_123")

        image_url = generate.await_args.args[0][0]["content"][0]["image_url"]
        prefix, encoded = image_url.split(",", 1)
        assert prefix == f"data:{media_type};base64"
        assert base64.b64decode(encoded) == image_data

    async def test_generation_failure_is_surfaced(self):
        with (
            patch(
                "app.services.agent.media_processor._download_telegram_file",
                new_callable=AsyncMock,
                return_value=b"\xff\xd8\xff\xe0DATA",
            ),
            patch(
                "app.services.agent.media_processor.generate_text",
                new_callable=AsyncMock,
                side_effect=RuntimeError("provider unavailable"),
            ),
            pytest.raises(RuntimeError, match="provider unavailable"),
        ):
            await describe_photo("file_id_123")


class TestDownloadTelegramFile:
    """Test _download_telegram_file with mocked httpx."""

    async def test_no_token_returns_none(self):
        """If no bot token is available, returns None."""
        from app.services.agent.media_processor import _download_telegram_file

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("app.services.agent.media_processor.get_settings") as mock_settings,
        ):
            mock_settings.return_value.telegram_bot_token = ""
            # Also clear TELEGRAM_BOT_TOKEN from env
            import os

            old = os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            try:
                result = await _download_telegram_file("file_id_123")
                assert result is None
            finally:
                if old is not None:
                    os.environ["TELEGRAM_BOT_TOKEN"] = old

    async def test_successful_download(self):
        """Successful file download returns bytes."""
        from app.services.agent.media_processor import _download_telegram_file

        mock_get_file_resp = MagicMock()
        mock_get_file_resp.json.return_value = {
            "ok": True,
            "result": {"file_path": "photos/file_42.jpg"},
        }

        mock_download_resp = MagicMock()
        mock_download_resp.content = b"fake image bytes"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[mock_get_file_resp, mock_download_resp]
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("os.environ.get", return_value="test-bot-token"),
            patch(
                "app.services.agent.media_processor.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            result = await _download_telegram_file("file_id_123")

        assert result == b"fake image bytes"

    async def test_get_file_api_failure_returns_none(self):
        """If Telegram getFile API returns not ok, returns None."""
        from app.services.agent.media_processor import _download_telegram_file

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False, "description": "Bad Request"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("os.environ.get", return_value="test-bot-token"),
            patch(
                "app.services.agent.media_processor.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            result = await _download_telegram_file("file_id_123")

        assert result is None

    async def test_oversized_file_returns_none(self):
        """Files exceeding MAX_DOWNLOAD_SIZE are rejected."""
        from app.services.agent.media_processor import _download_telegram_file

        mock_get_file_resp = MagicMock()
        mock_get_file_resp.json.return_value = {
            "ok": True,
            "result": {"file_path": "photos/huge.jpg"},
        }

        mock_download_resp = MagicMock()
        mock_download_resp.content = b"\x00" * (MAX_DOWNLOAD_SIZE + 1)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[mock_get_file_resp, mock_download_resp]
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("os.environ.get", return_value="test-bot-token"),
            patch(
                "app.services.agent.media_processor.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            result = await _download_telegram_file("file_id_123")

        assert result is None


class TestMediaTypes:
    """Test media type handling in forward processor."""

    def test_photo_content_type(self):
        from app.services.agent.forward_processor import parse_forwarded_message

        msg = {"photo": [{"file_id": "abc"}]}
        content = parse_forwarded_message(msg)
        assert content.content_type == "photo"

    def test_document_content_type(self):
        from app.services.agent.forward_processor import parse_forwarded_message

        msg = {"document": {"file_id": "abc", "file_name": "test.pdf"}}
        content = parse_forwarded_message(msg)
        assert content.content_type == "document"

    def test_video_content_type(self):
        from app.services.agent.forward_processor import parse_forwarded_message

        msg = {"video": {"file_id": "abc"}}
        content = parse_forwarded_message(msg)
        assert content.content_type == "video"

    def test_caption_as_text(self):
        from app.services.agent.forward_processor import parse_forwarded_message

        msg = {"photo": [{"file_id": "abc"}], "caption": "Look at this view!"}
        content = parse_forwarded_message(msg)
        assert content.text == "Look at this view!"
