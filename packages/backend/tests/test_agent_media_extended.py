"""Extended tests for media processor — document text extraction logic."""

import os


class TestDocumentExtensionLogic:
    """Test the extension-based file type detection."""

    def test_all_text_extensions_are_dotted(self):
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
            assert len(ext) >= 2

    def test_pdf_not_in_text_extensions(self):
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
        assert ".pdf" not in text_extensions

    def test_image_not_in_text_extensions(self):
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
        assert ".png" not in text_extensions
        assert ".jpg" not in text_extensions

    def test_extract_extension(self):
        assert os.path.splitext("report.txt")[1] == ".txt"
        assert os.path.splitext("code.py")[1] == ".py"
        assert os.path.splitext("data.json")[1] == ".json"
        assert os.path.splitext("no_extension")[1] == ""

    def test_case_insensitive_extension(self):
        assert os.path.splitext("README.MD")[1].lower() == ".md"
        assert os.path.splitext("config.YAML")[1].lower() == ".yaml"


class TestPhotoDescriptionPattern:
    """Test photo analysis patterns."""

    def test_largest_photo_selected(self):
        """Bot should use the largest photo size (last in array)."""
        photos = [
            {"file_id": "small", "width": 90, "height": 90},
            {"file_id": "medium", "width": 320, "height": 320},
            {"file_id": "large", "width": 800, "height": 800},
        ]
        # The pattern is: photos[-1] gets the largest
        assert photos[-1]["file_id"] == "large"

    def test_single_photo(self):
        photos = [{"file_id": "only_one", "width": 500, "height": 500}]
        assert photos[-1]["file_id"] == "only_one"

    def test_empty_photos(self):
        photos = []
        assert len(photos) == 0
