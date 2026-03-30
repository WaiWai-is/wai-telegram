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

PRESENTATION_PROMPT = """Generate a reveal.js presentation. Follow the template EXACTLY.

Topic: {description}

OUTPUT: Complete HTML starting with <!DOCTYPE html>. Use this EXACT structure:

<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>[TITLE]</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/theme/white.css">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {{ --accent: #4f46e5; }}
  .reveal {{ font-family: 'Inter', system-ui, sans-serif; }}
  .reveal h1 {{ font-size: 2.2em; font-weight: 800; color: #111; letter-spacing: -0.03em; line-height: 1.1; margin-bottom: 0.3em; }}
  .reveal h2 {{ font-size: 1.6em; font-weight: 700; color: #111; letter-spacing: -0.02em; margin-bottom: 0.5em; }}
  .reveal h3 {{ font-size: 1.1em; font-weight: 600; color: #6b7280; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 1em; }}
  .reveal p {{ font-size: 0.95em; color: #374151; line-height: 1.6; }}
  .reveal .slides section {{ text-align: left; padding: 60px 80px; }}
  .reveal ul {{ list-style: none; padding: 0; margin: 0; }}
  .reveal li {{ font-size: 0.95em; color: #374151; padding: 0.4em 0; padding-left: 1.5em; position: relative; }}
  .reveal li::before {{ content: ""; position: absolute; left: 0; top: 0.85em; width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }}
  .reveal .big-number {{ font-size: 4em; font-weight: 800; color: var(--accent); line-height: 1; }}
  .reveal .subtitle {{ font-size: 0.85em; color: #9ca3af; font-weight: 400; }}
  .reveal .dark-slide {{ background: #111 !important; color: #fff !important; }}
  .reveal .dark-slide h1, .reveal .dark-slide h2 {{ color: #fff; }}
  .reveal .dark-slide p, .reveal .dark-slide li {{ color: #d1d5db; }}
  .reveal .dark-slide li::before {{ background: #818cf8; }}
  .reveal .divider {{ width: 40px; height: 3px; background: var(--accent); margin: 1em 0; }}
  .reveal .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 40px; margin-top: 1em; }}
</style>
</head>
<body>
<div class="reveal"><div class="slides">

[GENERATE 8-12 <section> SLIDES HERE]

</div></div>
<script src="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.js"></script>
<script>Reveal.initialize({{ hash: true, transition: 'fade', center: false, width: 1200, height: 700, margin: 0.05 }});</script>
</body>
</html>

SLIDE TEMPLATES — use ONLY these patterns:

TITLE SLIDE:
<section style="text-align:center;display:flex;flex-direction:column;justify-content:center;align-items:center;height:100%;">
  <h3>CATEGORY OR DATE</h3>
  <h1>Main Title Here</h1>
  <p class="subtitle">One-line subtitle</p>
</section>

CONTENT SLIDE (bullets):
<section>
  <h2>Section Title</h2>
  <div class="divider"></div>
  <ul>
    <li>Short point one</li>
    <li>Short point two</li>
    <li>Short point three</li>
  </ul>
</section>

STAT SLIDE (big number):
<section>
  <h3>LABEL</h3>
  <div class="big-number">67%</div>
  <p>One line explaining this number</p>
</section>

DARK SLIDE (for emphasis):
<section class="dark-slide">
  <h2>Key Message</h2>
  <div class="divider" style="background:#818cf8"></div>
  <p>Supporting text goes here</p>
</section>

TWO-COLUMN SLIDE:
<section>
  <h2>Comparison Title</h2>
  <div class="two-col">
    <div><h3>LEFT</h3><ul><li>Point</li><li>Point</li></ul></div>
    <div><h3>RIGHT</h3><ul><li>Point</li><li>Point</li></ul></div>
  </div>
</section>

END SLIDE:
<section style="text-align:center;display:flex;flex-direction:column;justify-content:center;align-items:center;height:100%;">
  <h1>Thank You</h1>
  <p class="subtitle">contact@company.com</p>
</section>

RULES:
- NEVER use emoji. Zero. None.
- NEVER use gradients or bright colors.
- Keep text SHORT: max 8 words per bullet, max 4 bullets per slide.
- Use the EXACT CSS classes from above (.big-number, .dark-slide, .divider, .two-col, .subtitle).
- Mix slide types: title, 3-4 content, 2 stat, 1 dark, 1 two-col, end.
- All content must FIT within 1200x700px without overflow.

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
