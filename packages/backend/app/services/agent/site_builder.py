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

SITE_GENERATION_PROMPT = """You are a web developer. Generate a complete, beautiful, modern single-page website based on this description:

{description}

Requirements:
- Single HTML file with embedded CSS and JavaScript
- Modern, clean, responsive design (mobile-first)
- Beautiful typography and spacing
- Use a professional color scheme that fits the content
- Include all content from the description
- Add appropriate icons using emoji (no external icon libraries)
- The page must look professional and polished
- Do NOT use any external CDN links, frameworks, or fonts — everything inline
- Include a footer with "Made with Wai ✨"

Respond with ONLY the complete HTML code. No markdown, no explanation, just the HTML starting with <!DOCTYPE html>."""


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

    1. Generate HTML via Claude
    2. Save to /var/www/sites/{slug}/index.html
    3. Return the URL

    The nginx wildcard config serves it at {slug}.wai.computer.
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
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
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

        # Ensure it starts with DOCTYPE
        if not html.startswith("<!DOCTYPE") and not html.startswith("<html"):
            # Try to extract HTML from the response
            match = re.search(
                r"(<!DOCTYPE html.*</html>)", html, re.DOTALL | re.IGNORECASE
            )
            if match:
                html = match.group(1)
            else:
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

    # Save to filesystem
    try:
        site_dir.mkdir(parents=True, exist_ok=True)
        index_path = site_dir / "index.html"
        index_path.write_text(html, encoding="utf-8")

        url = f"https://{slug}.{DOMAIN}"
        logger.info(f"Site deployed: {url} → {site_dir}")

        return SiteResult(
            slug=slug,
            url=url,
            path=str(site_dir),
        )

    except Exception as e:
        logger.error(f"Site save failed: {e}")
        return SiteResult(
            slug=slug,
            url="",
            path="",
            success=False,
            error=f"Failed to save site: {e}",
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
