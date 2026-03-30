"""Tests for Presentation Builder — slug generation, HTML cleanup, result dataclass, prompt."""

import re
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.presentation_builder import (
    PRESENTATION_PROMPT,
    PresentationResult,
    build_presentation,
)
from app.services.agent.site_builder import generate_slug


class TestPresentationSlugGeneration:
    """Presentation slugs must have 'slides-' prefix and a uuid suffix."""

    def test_slug_has_slides_prefix(self):
        slug = generate_slug("Quarterly Review")
        slug = f"slides-{slug}"
        assert slug.startswith("slides-")

    def test_slug_preserves_content(self):
        slug = generate_slug("Team Standup")
        slug = f"slides-{slug}"
        assert "team-standup" in slug

    def test_slug_cyrillic_transliteration(self):
        slug = generate_slug("Отчёт за квартал")
        slug = f"slides-{slug}"
        assert slug.startswith("slides-")
        assert "otchyot" in slug or "otch" in slug

    def test_slug_special_chars_removed(self):
        slug = generate_slug("Q3 Report (Draft) #2!")
        slug = f"slides-{slug}"
        assert "(" not in slug
        assert ")" not in slug
        assert "#" not in slug
        assert "!" not in slug

    def test_slug_max_length(self):
        slug = generate_slug("A" * 100)
        slug = f"slides-{slug}"
        # generate_slug caps at 50, plus "slides-" = 57 max
        assert len(slug) <= 57


class TestPresentationHTMLCleanup:
    """Test markdown stripping logic used in build_presentation."""

    def test_strip_markdown_code_block_html(self):
        raw = "```html\n<!DOCTYPE html><html><body>Slides</body></html>\n```"
        html = raw.strip()
        if html.startswith("```"):
            html = re.sub(r"^```\w*\n?", "", html)
            html = re.sub(r"\n?```$", "", html)
            html = html.strip()
        assert html.startswith("<!DOCTYPE html>")
        assert "```" not in html

    def test_strip_plain_code_block(self):
        raw = "```\n<!DOCTYPE html><html></html>\n```"
        html = raw.strip()
        if html.startswith("```"):
            html = re.sub(r"^```\w*\n?", "", html)
            html = re.sub(r"\n?```$", "", html)
            html = html.strip()
        assert html.startswith("<!DOCTYPE html>")

    def test_extract_html_from_wrapped_text(self):
        raw = "Here is the presentation:\n<!DOCTYPE html><html><body><section>Slide 1</section></body></html>\nDone."
        html = raw.strip()
        if not html.startswith("<!DOCTYPE") and not html.startswith("<html"):
            match = re.search(
                r"(<!DOCTYPE html.*</html>)", html, re.DOTALL | re.IGNORECASE
            )
            if match:
                html = match.group(1)
        assert html.startswith("<!DOCTYPE html>")
        assert html.endswith("</html>")

    def test_clean_html_passes_through(self):
        clean = "<!DOCTYPE html><html><body><section>One</section></body></html>"
        html = clean.strip()
        if html.startswith("```"):
            html = re.sub(r"^```\w*\n?", "", html)
            html = re.sub(r"\n?```$", "", html)
            html = html.strip()
        assert html == clean


class TestPresentationPromptFormatting:
    """PRESENTATION_PROMPT must format without errors."""

    def test_format_basic(self):
        result = PRESENTATION_PROMPT.format(description="AI in Healthcare")
        assert "AI in Healthcare" in result

    def test_format_with_braces_in_description(self):
        # Ensure prompt handles normal text without crashing
        result = PRESENTATION_PROMPT.format(description="Sales Q3: revenue up 20%")
        assert "Sales Q3" in result

    def test_format_long_description_truncated(self):
        long_desc = "word " * 1000
        # Simulates what build_presentation does: description[:3000]
        result = PRESENTATION_PROMPT.format(description=long_desc[:3000])
        assert len(result) > 100

    def test_prompt_contains_revealjs(self):
        result = PRESENTATION_PROMPT.format(description="test")
        assert "reveal.js" in result

    def test_prompt_contains_structure_requirements(self):
        result = PRESENTATION_PROMPT.format(description="test")
        assert "Title slide" in result
        assert "8-12 content slides" in result


class TestPresentationResultDataclass:
    """PresentationResult must hold all expected fields."""

    def test_success_result(self):
        r = PresentationResult(
            slug="slides-demo-abc1", url="https://example.com", slide_count=10
        )
        assert r.success is True
        assert r.error is None
        assert r.slide_count == 10
        assert r.slug == "slides-demo-abc1"
        assert r.url == "https://example.com"
        assert isinstance(r.created_at, datetime)
        assert r.created_at.tzinfo is not None

    def test_failure_result(self):
        r = PresentationResult(
            slug="slides-fail-0000", url="", success=False, error="Deploy failed"
        )
        assert r.success is False
        assert r.error == "Deploy failed"
        assert r.slide_count == 0

    def test_default_created_at_is_utc(self):
        r = PresentationResult(slug="s", url="")
        # created_at should be timezone-aware (UTC)
        assert r.created_at.tzinfo is not None


class TestSlideCount:
    """Slide count extracted from <section> tags."""

    def test_count_sections(self):
        html = "<html><body><section>1</section><section>2</section><section>3</section></body></html>"
        count = html.lower().count("<section")
        assert count == 3

    def test_count_nested_sections(self):
        html = "<section><section>1</section><section>2</section></section>"
        count = html.lower().count("<section")
        assert count == 3

    def test_count_zero_when_no_sections(self):
        html = "<html><body><div>No slides</div></body></html>"
        count = html.lower().count("<section")
        assert count == 0


def _valid_presentation_html(slide_count: int = 5) -> str:
    """Build a valid reveal.js HTML that passes html_validator checks.

    Requirements: 200+ chars, DOCTYPE, <head></head>, </body>, </html>,
    contains 'reveal', and at least 3 <section> tags.
    """
    slides = "\n".join(
        f"<section><h2>Slide {i}</h2><p>Content for slide {i} goes here.</p></section>"
        for i in range(1, slide_count + 1)
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Test Presentation</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.css">
</head>
<body>
<div class="reveal"><div class="slides">
{slides}
</div></div>
<script src="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.js"></script>
<script>Reveal.initialize({{ hash: true }});</script>
</body>
</html>"""


class TestBuildPresentationIntegration:
    """Test build_presentation with mocked Claude API and deploy."""

    @pytest.mark.asyncio
    async def test_build_success(self):
        mock_html = _valid_presentation_html(5)
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=mock_html)]

        mock_deploy = AsyncMock(
            return_value={"success": True, "url": "https://slides-test.pages.dev"}
        )

        with (
            patch(
                "app.services.agent.presentation_builder.anthropic.AsyncAnthropic"
            ) as mock_cls,
            patch(
                "app.services.agent.presentation_builder.get_settings"
            ) as mock_settings,
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages", mock_deploy
            ),
        ):
            mock_settings.return_value.anthropic_api_key = "test-key"
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await build_presentation("AI Overview")

        assert result.slug.startswith("slides-")
        assert result.slide_count == 5
        assert result.success is True
        assert result.url == "https://slides-test.pages.dev"

    @pytest.mark.asyncio
    async def test_build_api_failure(self):
        with (
            patch(
                "app.services.agent.presentation_builder.anthropic.AsyncAnthropic"
            ) as mock_cls,
            patch(
                "app.services.agent.presentation_builder.get_settings"
            ) as mock_settings,
        ):
            mock_settings.return_value.anthropic_api_key = "test-key"
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(side_effect=Exception("API down"))
            mock_cls.return_value = mock_client

            result = await build_presentation("Test topic")

        assert result.success is False
        assert "API down" in result.error
        assert result.slug.startswith("slides-")

    @pytest.mark.asyncio
    async def test_build_invalid_html(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Sorry, I can't generate that.")]

        with (
            patch(
                "app.services.agent.presentation_builder.anthropic.AsyncAnthropic"
            ) as mock_cls,
            patch(
                "app.services.agent.presentation_builder.get_settings"
            ) as mock_settings,
        ):
            mock_settings.return_value.anthropic_api_key = "test-key"
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await build_presentation("Bad request")

        assert result.success is False
        assert "valid presentation HTML" in result.error

    @pytest.mark.asyncio
    async def test_build_deploy_failure(self):
        mock_html = _valid_presentation_html(4)
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=mock_html)]

        mock_deploy = AsyncMock(
            return_value={"success": False, "error": "Credentials missing"}
        )

        with (
            patch(
                "app.services.agent.presentation_builder.anthropic.AsyncAnthropic"
            ) as mock_cls,
            patch(
                "app.services.agent.presentation_builder.get_settings"
            ) as mock_settings,
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages", mock_deploy
            ),
        ):
            mock_settings.return_value.anthropic_api_key = "test-key"
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await build_presentation("Test")

        assert result.success is False
        assert "Credentials" in result.error or "Deploy" in result.error

    @pytest.mark.asyncio
    async def test_build_too_few_slides_fails_validation(self):
        """HTML with < 3 sections should fail presentation validation."""
        mock_html = _valid_presentation_html(2)
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=mock_html)]

        with (
            patch(
                "app.services.agent.presentation_builder.anthropic.AsyncAnthropic"
            ) as mock_cls,
            patch(
                "app.services.agent.presentation_builder.get_settings"
            ) as mock_settings,
        ):
            mock_settings.return_value.anthropic_api_key = "test-key"
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await build_presentation("Minimal deck")

        assert result.success is False
        assert "slides found" in result.error
