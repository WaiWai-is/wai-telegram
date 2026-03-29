"""Site Builder — generate and deploy websites from Telegram prompts.

User sends: "Сделай лендинг для кафе Рассвет. Меню: кофе 300р, латте 400р."
Wai generates HTML → saves to /var/www/sites/{slug}/ → accessible at {slug}.wai.computer

Architecture:
- Claude generates complete HTML/CSS/JS (single page, no build step)
- Saved to filesystem (nginx serves static files)
- Wildcard nginx config routes *.wai.computer to the right directory
- Each site gets a unique slug (auto-generated from name)
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import anthropic

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Where sites are stored on the server
SITES_DIR = Path("/var/www/sites")
DOMAIN = "wai.computer"

SITE_GENERATION_PROMPT = """Generate a stunning, modern single-page website.

Description: {description}

TECH STACK (use these CDNs in <head>):
- Tailwind CSS: <script src="https://cdn.tailwindcss.com"></script>
- Google Fonts: pick 1-2 fonts that fit the vibe
- Lucide Icons: <script src="https://unpkg.com/lucide@latest"></script> then <i data-lucide="icon-name"></i>
- Alpine.js + Intersect plugin (BOTH required):
  <script defer src="https://cdn.jsdelivr.net/npm/@alpinejs/intersect@3.x.x/dist/cdn.min.js"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>

REQUIREMENTS:
- Single HTML file, all content inline
- Hero section with bold headline and CTA
- At least 4 content sections (services/features, about, testimonials, contact)
- ALL sections must be visible by default. Use Alpine x-intersect ONLY for adding animations, NOT for showing/hiding content. Example: x-data="{ shown: true }" x-intersect="shown = true" :class="shown ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'" class="transition duration-700"
- Mobile-responsive (Tailwind handles this)
- Professional color scheme fitting the business
- Footer with "Made with Wai ✨"

OUTPUT: Only the HTML starting with <!DOCTYPE html>. No markdown, no explanation."""


@dataclass
class SiteResult:
    slug: str
    url: str
    path: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    success: bool = True
    error: str | None = None


def generate_slug(name: str) -> str:
    """Generate a URL-safe slug from a name."""
    # Transliterate common Cyrillic
    translit = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "yo",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "kh",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "shch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
    slug = name.lower().strip()
    result = []
    for char in slug:
        if char in translit:
            result.append(translit[char])
        elif char.isascii() and char.isalnum():
            result.append(char)
        elif char in " -_":
            result.append("-")
    slug = "".join(result)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:50] or f"site-{uuid4().hex[:8]}"


async def build_site(description: str, name: str | None = None) -> SiteResult:
    """Generate and deploy a website from a text description.

    Strategy: Agent SDK (Claude Code-like) → Direct API call fallback.
    Deploy: Cloudflare Pages → local filesystem fallback.
    """
    settings = get_settings()

    # Generate slug
    slug = generate_slug(name or description[:30])

    # Ensure no collision
    site_dir = SITES_DIR / slug
    if site_dir.exists():
        slug = f"{slug}-{uuid4().hex[:4]}"
        site_dir = SITES_DIR / slug

    # Generate HTML via Claude
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16384,
            messages=[
                {
                    "role": "user",
                    "content": SITE_GENERATION_PROMPT.format(
                        description=description[:3000]
                    ),
                }
            ],
        )
        html = response.content[0].text.strip()

        # Strip markdown code blocks (Claude often wraps in ```html ... ```)
        if html.startswith("```"):
            # Remove opening ```html or ```
            html = re.sub(r"^```\w*\n?", "", html)
            # Remove closing ```
            html = re.sub(r"\n?```$", "", html)
            html = html.strip()

        # Extract HTML if still wrapped in text
        if not html.startswith("<!DOCTYPE") and not html.startswith("<html"):
            match = re.search(
                r"(<!DOCTYPE html.*</html>)", html, re.DOTALL | re.IGNORECASE
            )
            if match:
                html = match.group(1)
            else:
                logger.error(f"Invalid HTML output (first 200 chars): {html[:200]}")
                return SiteResult(
                    slug=slug,
                    url="",
                    path="",
                    success=False,
                    error="Failed to generate valid HTML",
                )

    except Exception as e:
        logger.error(f"Site generation failed: {e}")
        return SiteResult(
            slug=slug,
            url="",
            path="",
            success=False,
            error=f"AI generation failed: {e}",
        )

    # Deploy: try Cloudflare Pages first, fall back to local filesystem
    from app.services.agent.cloudflare_deploy import deploy_site_to_pages

    deploy_result = await deploy_site_to_pages(slug, html)

    if deploy_result["success"]:
        url = deploy_result["url"]
        method = deploy_result.get("method", "cloudflare")
        logger.info(f"Site deployed ({method}): {url}")
        return SiteResult(
            slug=slug,
            url=url,
            path=url,
        )
    else:
        return SiteResult(
            slug=slug,
            url="",
            path="",
            success=False,
            error=deploy_result.get("error", "Deploy failed"),
        )


async def list_user_sites(sites_dir: Path = SITES_DIR) -> list[dict]:
    """List all deployed sites."""
    sites = []
    if not sites_dir.exists():
        return sites
    for d in sorted(sites_dir.iterdir()):
        if d.is_dir() and (d / "index.html").exists():
            stat = (d / "index.html").stat()
            sites.append(
                {
                    "slug": d.name,
                    "url": f"https://{d.name}.{DOMAIN}",
                    "size": stat.st_size,
                    "created": datetime.fromtimestamp(
                        stat.st_ctime, tz=UTC
                    ).isoformat(),
                }
            )
    return sites


async def delete_site(slug: str) -> bool:
    """Delete a deployed site."""
    import shutil

    site_dir = SITES_DIR / slug
    if not site_dir.exists():
        return False
    shutil.rmtree(site_dir)
    logger.info(f"Site deleted: {slug}")
    return True
