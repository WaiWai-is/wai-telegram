"""Tests for Inline Mode — the viral mechanic."""

from app.services.agent.inline import _make_article


class TestMakeArticle:
    def test_basic_article(self):
        article = _make_article(
            title="Test Title",
            description="Test Description",
            text="Test message text",
        )
        assert article["type"] == "article"
        assert article["title"] == "Test Title"
        assert article["description"] == "Test Description"
        assert article["input_message_content"]["message_text"] == "Test message text"
        assert article["input_message_content"]["parse_mode"] == "Markdown"

    def test_article_has_unique_id(self):
        a1 = _make_article("Title 1", "Desc 1", "Text 1")
        a2 = _make_article("Title 2", "Desc 2", "Text 2")
        assert a1["id"] != a2["id"]

    def test_same_content_same_id(self):
        a1 = _make_article("Same", "Same", "Text")
        a2 = _make_article("Same", "Same", "Text")
        assert a1["id"] == a2["id"]

    def test_long_title_truncated(self):
        article = _make_article("A" * 100, "desc", "text")
        assert len(article["title"]) <= 64

    def test_long_description_truncated(self):
        article = _make_article("title", "B" * 200, "text")
        assert len(article["description"]) <= 128

    def test_long_text_truncated(self):
        article = _make_article("title", "desc", "C" * 5000)
        assert len(article["input_message_content"]["message_text"]) <= 4096

    def test_article_structure(self):
        article = _make_article("t", "d", "m")
        assert "type" in article
        assert "id" in article
        assert "title" in article
        assert "description" in article
        assert "input_message_content" in article
        assert "message_text" in article["input_message_content"]
