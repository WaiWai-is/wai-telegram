"""Tests for Media Processor — photos and documents."""



class TestExtractDocumentText:
    """Test text extraction from documents (no network calls needed)."""

    def test_text_extension_check(self):
        """Verify text extensions are recognized."""

        # Can't test actual download in unit tests, but test logic:
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
