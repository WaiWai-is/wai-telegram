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

PRESENTATION_PROMPT = """Generate a sophisticated, minimalist reveal.js presentation.

Topic: {description}

TECH STACK (include in <head>):
- reveal.js: <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.css">
- Use the WHITE theme as base: <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/theme/white.css">
- reveal.js JS: <script src="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.js"></script>
- Google Fonts: use 2 fonts — one elegant heading font (e.g. DM Serif Display, Fraunces, Playfair Display) + one clean body font (e.g. Inter, DM Sans, Plus Jakarta Sans)

CRITICAL DESIGN RULES — follow these strictly:

  NEVER use emoji. Zero emoji anywhere. Use typography, whitespace, and color instead.

  Color palette — pick ONE accent color (muted, sophisticated) + near-black text (#1a1a1a) + white/off-white bg:
    Good accents: #4f46e5 (indigo), #0f766e (teal), #b91c1c (deep red), #7c3aed (purple), #0369a1 (blue)
    BAD: pink, neon green, bright orange, rainbow gradients

  Typography:
    - Headings: the serif/display font, 2.5em-3em, font-weight 700, letter-spacing -0.02em
    - Body text: the sans font, 1.2em, font-weight 400, line-height 1.6, color #374151
    - Numbers/stats: the sans font, 4-6em, font-weight 800, accent color
    - Captions: 0.9em, color #6b7280

  Layout per slide:
    - Max 60% of slide width for text (leave breathing room)
    - Left-aligned text (NOT centered) for content slides. Only title slide is centered.
    - One idea per slide. Max 3-4 bullet points. Short phrases, NOT sentences.
    - Use thin horizontal lines (1px, #e5e7eb) as dividers

  Visual hierarchy:
    - Title slide: large heading + small subtitle + date. Nothing else.
    - Data slides: ONE big number (4-6em) + one-line explanation below
    - Content slides: heading + 2-4 short bullet points
    - Quote slides: large italic text + attribution
    - Final slide: "Thank you" or clear CTA. Clean, minimal.

  Backgrounds:
    - Most slides: white or #fafafa
    - 1-2 accent slides: solid dark background (#1e293b or #0f172a) with white text
    - NO gradients, NO patterns, NO neon

  Slide transitions: data-transition="fade" (subtle, not distracting)

STRUCTURE:
- Title slide (centered)
- 8-12 content slides (left-aligned)
- Final "Thank you" or CTA slide
- Speaker notes: <aside class="notes">...</aside>

CUSTOM CSS (override reveal.js defaults in <style>):
  .reveal h1, .reveal h2 {{ font-family: 'HEADING_FONT', serif; color: #1a1a1a; }}
  .reveal p, .reveal li {{ font-family: 'BODY_FONT', sans-serif; color: #374151; text-align: left; }}
  .reveal .slides section {{ padding: 40px 80px; }}
  .reveal ul {{ list-style: none; padding: 0; }}
  .reveal li::before {{ content: "—"; color: ACCENT; margin-right: 12px; font-weight: 700; }}
  .reveal .stat {{ font-size: 5em; font-weight: 800; color: ACCENT; line-height: 1; }}

INIT (before </body>):
<script>
Reveal.initialize({{
  hash: true,
  transition: 'fade',
  center: false,
  width: 1200,
  height: 700,
  margin: 0.04
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
            model="claude-sonnet-4-6",
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

        # Validate before deploy
        from app.services.agent.html_validator import validate_html

        is_valid, validation_error = validate_html(html, "presentation")
        if not is_valid:
            logger.error(f"Presentation validation failed: {validation_error}")
            return PresentationResult(
                slug=slug,
                url="",
                success=False,
                error=f"Quality check failed: {validation_error}",
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
