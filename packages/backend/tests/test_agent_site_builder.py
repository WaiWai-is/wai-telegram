"""Tests for Site Builder — generate and deploy websites."""

from app.services.agent.site_builder import generate_slug


class TestGenerateSlug:
    def test_english_name(self):
        assert generate_slug("My Cafe") == "my-cafe"

    def test_russian_name(self):
        slug = generate_slug("Кафе Рассвет")
        assert slug == "kafe-rassvet"

    def test_mixed_name(self):
        slug = generate_slug("Кафе Coffee House")
        assert "kafe" in slug
        assert "coffee" in slug

    def test_special_chars_removed(self):
        slug = generate_slug("Café & Bar #1!")
        assert "&" not in slug
        assert "#" not in slug
        assert "!" not in slug

    def test_multiple_dashes_collapsed(self):
        slug = generate_slug("My   Big   Cafe")
        assert "--" not in slug

    def test_max_length(self):
        slug = generate_slug("A" * 100)
        assert len(slug) <= 50

    def test_empty_string(self):
        slug = generate_slug("")
        assert slug.startswith("site-")
        assert len(slug) > 5

    def test_only_special_chars(self):
        slug = generate_slug("!@#$%")
        assert slug.startswith("site-")

    def test_trim_dashes(self):
        slug = generate_slug("--hello--")
        assert not slug.startswith("-")
        assert not slug.endswith("-")

    def test_cyrillic_transliteration(self):
        assert "zh" in generate_slug("Жизнь")
        assert "sh" in generate_slug("Шоколад")
        assert "ch" in generate_slug("Чай")

    def test_numbers_preserved(self):
        slug = generate_slug("Cafe 42")
        assert "42" in slug

    def test_url_safe(self):
        slug = generate_slug("Test / Site @ 2026")
        assert "/" not in slug
        assert "@" not in slug
        assert " " not in slug
