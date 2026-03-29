"""Tests for presentation_builder — slide generation and validation."""

from app.services.agent.presentation_builder import (
    PresentationResult,
    PRESENTATION_PROMPT,
)
from app.services.agent.site_builder import generate_slug


class TestPresentationPrompt:
    def test_prompt_formats_correctly(self):
        """Prompt should accept {description} without errors."""
        result = PRESENTATION_PROMPT.format(description="Test pitch deck")
        assert "Test pitch deck" in result
        assert "reveal.js" in result

    def test_prompt_escapes_braces(self):
        """Double braces in Reveal.initialize should survive .format()."""
        result = PRESENTATION_PROMPT.format(description="test")
        assert "Reveal.initialize({" in result
        assert "hash: true" in result

    def test_prompt_contains_cdns(self):
        result = PRESENTATION_PROMPT.format(description="test")
        assert "cdn.jsdelivr.net" in result
        assert "reveal.js" in result

    def test_prompt_russian_description(self):
        result = PRESENTATION_PROMPT.format(description="Презентация про AI стартап")
        assert "Презентация про AI стартап" in result


class TestPresentationResult:
    def test_defaults(self):
        r = PresentationResult(slug="test", url="https://example.com")
        assert r.success is True
        assert r.error is None
        assert r.slide_count == 0

    def test_failure(self):
        r = PresentationResult(slug="test", url="", success=False, error="fail")
        assert not r.success
        assert r.error == "fail"


class TestSlugGeneration:
    def test_slug_from_english(self):
        slug = generate_slug("Pitch deck for AI startup")
        assert slug == "pitch-deck-for-ai-startup"

    def test_slug_from_russian(self):
        slug = generate_slug("Презентация для стартапа")
        assert "prezentatsiya" in slug or "prezentaciya" in slug or len(slug) > 5

    def test_slug_max_length(self):
        slug = generate_slug("A" * 100)
        assert len(slug) <= 50
