"""Presentation Builder — generate reveal.js presentations from text descriptions.

Same pattern as site_builder: Claude generates HTML → deploy to Cloudflare Pages.
Uses reveal.js CDN for a professional slide deck in a single HTML file.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import anthropic

from app.core.config import get_settings
from app.services.agent.site_builder import generate_slug

logger = logging.getLogger(__name__)

PRESENTATION_PROMPT = """Generate a stunning reveal.js presentation as a single HTML file.

Topic: {description}

TECH STACK (include in <head>):
- reveal.js CSS: <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.css">
- Theme: <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/theme/black.css"> (or white/moon/night — pick what fits)
- reveal.js JS: <script src="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.js"></script>
- Google Fonts: pick 1 font that fits the vibe

STRUCTURE:
- Title slide with bold headline, subtitle, date
- 8-15 content slides
- Each slide has ONE clear idea, minimal text
- Use bullet points sparingly (max 4 per slide)
- Include a "Thank you" / Q&A final slide
- Add speaker notes where helpful: <aside class="notes">...</aside>

DESIGN:
- Clean, modern, professional
- Use emoji or Unicode symbols for visual interest
- Background gradients or colors per section
- Large font sizes, high contrast
- Slide transitions: data-transition="slide" or "fade"

INIT (before </body>):
<script>
Reveal.initialize({{
  hash: true,
  transition: 'slide',
  center: true
}});
</script>

OUTPUT: Only the HTML starting with <!DOCTYPE html>. No markdown wrapping."""


@dataclass
class PresentationResult:
    slug: str
    url: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    success: bool = True
    error: str | None = None
    slide_count: int = 0


async def build_presentation(
    description: str, name: str | None = None
) -> PresentationResult:
    """Generate and deploy a reveal.js presentation."""
    settings = get_settings()

    slug = generate_slug(name or description[:30])
    slug = f"slides-{slug}"

    # Deduplicate
    slug = f"{slug}-{uuid4().hex[:4]}"

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16384,
            messages=[
                {
                    "role": "user",
                    "content": PRESENTATION_PROMPT.format(
                        description=description[:3000]
                    ),
                }
            ],
        )
        html = response.content[0].text.strip()

        # Strip markdown code blocks
        if html.startswith("```"):
            html = re.sub(r"^```\w*\n?", "", html)
            html = re.sub(r"\n?```$", "", html)
            html = html.strip()

        # Extract HTML if wrapped
        if not html.startswith("<!DOCTYPE") and not html.startswith("<html"):
            match = re.search(
                r"(<!DOCTYPE html.*</html>)", html, re.DOTALL | re.IGNORECASE
            )
            if match:
                html = match.group(1)
            else:
                logger.error(f"Invalid HTML output: {html[:200]}")
                return PresentationResult(
                    slug=slug,
                    url="",
                    success=False,
                    error="Failed to generate valid presentation HTML",
                )

        # Count slides
        slide_count = html.lower().count("<section")

    except Exception as e:
        logger.error(f"Presentation generation failed: {e}")
        return PresentationResult(
            slug=slug,
            url="",
            success=False,
            error=f"AI generation failed: {e}",
        )

    # Deploy to Cloudflare Pages
    from app.services.agent.cloudflare_deploy import deploy_site_to_pages

    deploy_result = await deploy_site_to_pages(slug, html)

    if deploy_result["success"]:
        url = deploy_result["url"]
        logger.info(f"Presentation deployed: {url} ({slide_count} slides)")
        return PresentationResult(
            slug=slug,
            url=url,
            slide_count=slide_count,
        )
    else:
        return PresentationResult(
            slug=slug,
            url="",
            success=False,
            error=deploy_result.get("error", "Deploy failed"),
        )
