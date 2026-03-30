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

_redis_client = None
_SITE_STORE_TTL = 86400 * 7  # 7 days
_SITES_LIST_TTL = 86400 * 30  # 30 days


def _get_redis():
    """Get Redis client for site store (survives server restarts)."""
    global _redis_client
    if _redis_client is None:
        import redis

        _redis_client = redis.from_url(get_settings().redis_url)
    return _redis_client


SITE_EDIT_PROMPT = (
    "Here is the current HTML of a website. Apply the following changes: {instruction}. "
    "Return the COMPLETE updated HTML. Do not explain, just output the full HTML "
    "starting with <!DOCTYPE html>."
)

# ---------------------------------------------------------------------------
# Theme presets — each provides Tailwind classes, Google Fonts, and color specs
# that get injected into the generation prompt.
# ---------------------------------------------------------------------------
THEMES: dict[str, dict] = {
    "default": {
        "name": "default",
        "description": "Let Claude pick the best color scheme based on the content.",
        "prompt": "",
        "keywords_en": [],
        "keywords_ru": [],
    },
    "dark-corporate": {
        "name": "dark-corporate",
        "description": "Dark background with white text and blue accents — sleek, professional.",
        "prompt": (
            "THEME (override all default colors and fonts with these):\n"
            "- Background: dark navy (#0f172a), cards: (#1e293b)\n"
            "- Text: white (#f8fafc) for headings, slate-300 (#cbd5e1) for body\n"
            "- Accents: blue-500 (#3b82f6) for CTAs, blue-400 (#60a5fa) for links\n"
            "- Google Font: <link href='https://fonts.googleapis.com/css2?"
            "family=Inter:wght@400;600;700&display=swap' rel='stylesheet'>\n"
            "- Tailwind: body bg-slate-900 text-slate-300, headings text-white font-semibold\n"
            "- Buttons: bg-blue-500 hover:bg-blue-600 text-white rounded-lg\n"
            "- Cards: bg-slate-800 border border-slate-700 rounded-xl\n"
            "- Footer: bg-slate-950 text-slate-400\n"
        ),
        "keywords_en": ["dark", "corporate", "professional", "dark theme", "navy"],
        "keywords_ru": [
            "тёмная",
            "темная",
            "корпоративная",
            "тёмная тема",
            "темная тема",
        ],
    },
    "warm-organic": {
        "name": "warm-organic",
        "description": "Cream background with brown/amber accents and serif headings.",
        "prompt": (
            "THEME (override all default colors and fonts with these):\n"
            "- Background: warm cream (#faf7f2), cards: white (#ffffff)\n"
            "- Text: brown-900 (#3b1f0b) for headings, brown-700 (#5c3a1e) for body\n"
            "- Accents: amber-600 (#d97706) for CTAs, amber-700 (#b45309) for links\n"
            "- Google Font: <link href='https://fonts.googleapis.com/css2?"
            "family=Merriweather:wght@400;700&family=Source+Sans+3:wght@400;600&display=swap' "
            "rel='stylesheet'>\n"
            "- Headings: font-family 'Merriweather', serif. Body: 'Source Sans 3', sans-serif\n"
            "- Tailwind: body bg-[#faf7f2] text-[#5c3a1e]\n"
            "- Buttons: bg-amber-600 hover:bg-amber-700 text-white rounded-full\n"
            "- Cards: bg-white shadow-md rounded-2xl border border-amber-100\n"
        ),
        "keywords_en": ["warm", "organic", "natural", "earthy", "cream"],
        "keywords_ru": ["тёплая", "теплая", "органическая", "натуральная", "кремовая"],
    },
    "neon-startup": {
        "name": "neon-startup",
        "description": "Dark background with neon green/purple gradients and monospace accents.",
        "prompt": (
            "THEME (override all default colors and fonts with these):\n"
            "- Background: near-black (#0a0a0a), cards: (#18181b)\n"
            "- Text: white (#ffffff) for headings, zinc-400 (#a1a1aa) for body\n"
            "- Accents: neon green (#22c55e) and purple (#a855f7), gradients green-to-purple\n"
            "- Google Font: <link href='https://fonts.googleapis.com/css2?"
            "family=JetBrains+Mono:wght@400;700&family=Space+Grotesk:wght@400;600;700"
            "&display=swap' rel='stylesheet'>\n"
            "- Headings: font-family 'Space Grotesk', sans-serif. "
            "Code/accents: 'JetBrains Mono', monospace\n"
            "- Tailwind: body bg-zinc-950 text-zinc-400\n"
            "- Buttons: bg-gradient-to-r from-green-500 to-purple-500 text-white rounded-lg\n"
            "- Cards: bg-zinc-900 border border-zinc-800 rounded-xl, subtle glow on hover\n"
        ),
        "keywords_en": ["neon", "startup", "tech", "cyberpunk", "glow"],
        "keywords_ru": ["неон", "стартап", "технологичная", "киберпанк"],
    },
    "clean-minimal": {
        "name": "clean-minimal",
        "description": "White background, black text, lots of whitespace, Inter font.",
        "prompt": (
            "THEME (override all default colors and fonts with these):\n"
            "- Background: white (#ffffff), cards: gray-50 (#f9fafb)\n"
            "- Text: gray-900 (#111827) for headings, gray-600 (#4b5563) for body\n"
            "- Accents: gray-900 (#111827) for CTAs, underline links instead of colored\n"
            "- Google Font: <link href='https://fonts.googleapis.com/css2?"
            "family=Inter:wght@400;500;600;700&display=swap' rel='stylesheet'>\n"
            "- Font: 'Inter', sans-serif everywhere\n"
            "- Tailwind: body bg-white text-gray-600, generous py-24 px-6 spacing\n"
            "- Buttons: bg-gray-900 hover:bg-gray-800 text-white rounded-md\n"
            "- Cards: bg-gray-50 rounded-lg, minimal borders. Lots of whitespace.\n"
        ),
        "keywords_en": ["minimal", "minimalist", "clean", "simple", "white"],
        "keywords_ru": ["минимализм", "минималистичная", "чистая", "простая", "белая"],
    },
    "luxury-gold": {
        "name": "luxury-gold",
        "description": "Black background with gold accents and elegant serif fonts.",
        "prompt": (
            "THEME (override all default colors and fonts with these):\n"
            "- Background: black (#000000), cards: (#111111)\n"
            "- Text: gold (#d4af37) for headings, gray-300 (#d1d5db) for body\n"
            "- Accents: gold (#d4af37) for borders/highlights, white for CTAs\n"
            "- Google Font: <link href='https://fonts.googleapis.com/css2?"
            "family=Playfair+Display:wght@400;600;700&family=Lato:wght@300;400;700"
            "&display=swap' rel='stylesheet'>\n"
            "- Headings: 'Playfair Display', serif. Body: 'Lato', sans-serif, font-weight 300\n"
            "- Tailwind: body bg-black text-gray-300\n"
            "- Buttons: border-2 border-[#d4af37] text-[#d4af37] "
            "hover:bg-[#d4af37] hover:text-black rounded-none uppercase tracking-widest\n"
            "- Cards: bg-[#111111] border border-[#d4af37]/20 rounded-none\n"
        ),
        "keywords_en": ["luxury", "gold", "elegant", "premium", "luxurious"],
        "keywords_ru": [
            "люкс",
            "золото",
            "золотая",
            "элегантная",
            "премиум",
            "роскошная",
        ],
    },
    "fresh-modern": {
        "name": "fresh-modern",
        "description": "White background with vibrant blue/green, rounded corners, playful.",
        "prompt": (
            "THEME (override all default colors and fonts with these):\n"
            "- Background: white (#ffffff), cards: blue-50 (#eff6ff) or green-50 (#f0fdf4)\n"
            "- Text: gray-800 (#1f2937) for headings, gray-600 (#4b5563) for body\n"
            "- Accents: vibrant blue (#2563eb) and teal (#0d9488), use gradients\n"
            "- Google Font: <link href='https://fonts.googleapis.com/css2?"
            "family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap' rel='stylesheet'>\n"
            "- Font: 'Plus Jakarta Sans', sans-serif everywhere\n"
            "- Tailwind: body bg-white text-gray-600\n"
            "- Buttons: bg-blue-600 hover:bg-blue-700 text-white rounded-full px-8\n"
            "- Cards: bg-blue-50 rounded-2xl shadow-sm, rounded-3xl for hero sections\n"
        ),
        "keywords_en": ["fresh", "modern", "vibrant", "colorful", "playful"],
        "keywords_ru": ["свежая", "современная", "яркая", "красочная", "игривая"],
    },
    "retro-vintage": {
        "name": "retro-vintage",
        "description": "Warm sepia tones, vintage serif fonts, textured feel.",
        "prompt": (
            "THEME (override all default colors and fonts with these):\n"
            "- Background: warm sepia (#f5f0e8), cards: (#fffdf7)\n"
            "- Text: dark brown (#2d1b0e) for headings, brown (#5c4033) for body\n"
            "- Accents: rust (#b7410e) for CTAs, dark olive (#556b2f) for secondary\n"
            "- Google Font: <link href='https://fonts.googleapis.com/css2?"
            "family=Libre+Baskerville:wght@400;700&family=Courier+Prime&display=swap' "
            "rel='stylesheet'>\n"
            "- Headings: 'Libre Baskerville', serif. Body accents: 'Courier Prime', monospace\n"
            "- Tailwind: body bg-[#f5f0e8] text-[#5c4033]\n"
            "- Buttons: bg-[#b7410e] hover:bg-[#8b3209] text-white rounded-sm "
            "uppercase tracking-wider\n"
            "- Cards: bg-[#fffdf7] border border-[#d4c5a9] rounded-sm shadow-sm\n"
        ),
        "keywords_en": ["retro", "vintage", "old-school", "classic", "nostalgic"],
        "keywords_ru": [
            "ретро",
            "винтажная",
            "классическая",
            "старинная",
            "ностальгическая",
        ],
    },
}


def detect_theme(text: str) -> str:
    """Detect a theme from user text by matching keywords.

    Scans for keyword matches in the description.
    Returns the theme key, or "default" if nothing matches.
    """
    lower = text.lower()
    for theme_key, theme in THEMES.items():
        if theme_key == "default":
            continue
        for kw in theme["keywords_en"] + theme["keywords_ru"]:
            if kw in lower:
                return theme_key
    return "default"


def parse_theme_flag(text: str) -> tuple[str, str]:
    """Parse --theme flag from the description text.

    Returns (theme_key, remaining_description).
    If --theme is not present or value is unknown, returns ("", original_text).
    """
    match = re.match(r"--theme\s+([\w-]+)\s*(.*)", text, re.DOTALL)
    if match:
        theme_key = match.group(1).lower()
        remaining = match.group(2).strip()
        if theme_key in THEMES:
            return theme_key, remaining
        return "", text
    return "", text


def resolve_theme(description: str) -> tuple[str, str]:
    """Resolve the theme for a build request.

    Checks --theme flag first, then auto-detects from keywords.
    Returns (theme_key, cleaned_description).
    """
    # 1. Explicit --theme flag takes priority
    theme_key, remaining = parse_theme_flag(description)
    if theme_key:
        return theme_key, remaining

    # 2. Auto-detect from description keywords
    detected = detect_theme(description)
    return detected, description


def get_theme_prompt(theme_key: str) -> str:
    """Get the prompt injection text for a theme.

    Returns empty string for "default" theme (let Claude decide).
    """
    theme = THEMES.get(theme_key)
    if not theme or theme_key == "default":
        return ""
    return theme["prompt"]


SITE_GENERATION_PROMPT = """Generate a stunning, modern single-page website.

Description: {description}
{theme_instructions}
TECH STACK (use these CDNs in <head>):
- Tailwind CSS: <script src="https://cdn.tailwindcss.com"></script>
- Google Fonts: pick 1-2 fonts that fit the vibe (or use the theme-specified fonts if a THEME section is provided above)
- Lucide Icons: <script src="https://unpkg.com/lucide@latest"></script> then <i data-lucide="icon-name"></i>
- Alpine.js + Intersect plugin (BOTH required):
  <script defer src="https://cdn.jsdelivr.net/npm/@alpinejs/intersect@3.x.x/dist/cdn.min.js"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>

SEO (include in <head>):
- <meta name="description" content="..."> with a compelling 150-char summary
- <meta property="og:title" content="...">
- <meta property="og:description" content="...">
- <meta property="og:type" content="website">
- <meta name="twitter:card" content="summary_large_image">
- <meta name="twitter:title" content="...">
- <meta name="twitter:description" content="...">
- <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🌐</text></svg>">

IMAGES (use real photos, NOT just gradients):
- For hero backgrounds, about sections, and visual content use picsum.photos:
  <img src="https://picsum.photos/seed/DESCRIPTIVE-SEED/1200/800" loading="lazy" class="w-full h-full object-cover" alt="...">
- Seeds should describe the content: seed/coffee-shop, seed/team-work, seed/modern-office, seed/yoga-studio
- ALWAYS add loading="lazy" and descriptive alt text
- Use object-fit: cover with rounded corners for cards

DESIGN SYSTEM (follow these rules strictly for consistent, premium output):

  Spacing scale — use ONLY these vertical paddings for sections:
  - Hero section: py-24 md:py-32
  - Major content sections: py-16 md:py-24
  - Minor/compact sections: py-12 md:py-16
  - Inside cards and containers: p-6 md:p-8
  - Grid gap between items: gap-6 md:gap-8
  - Space between heading and content: mb-12 md:mb-16

  Container — every section's content sits inside:
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">

  Typography hierarchy:
  - h1 (hero): text-4xl md:text-5xl lg:text-6xl font-bold tracking-tight leading-tight
  - h2 (section titles): text-3xl md:text-4xl font-bold tracking-tight
  - h3 (card/item titles): text-xl md:text-2xl font-semibold
  - Body text: text-base md:text-lg leading-relaxed text-gray-600 (or light equivalent)
  - Small/caption: text-sm text-gray-500
  - Section subtitles: text-lg md:text-xl text-gray-600 max-w-2xl mx-auto (centered under h2)

COMPONENT PATTERNS (use these exact patterns):

  Cards:
  <div class="bg-white rounded-2xl shadow-lg hover:shadow-xl transition-shadow duration-300 p-6 md:p-8">
    ...content...
  </div>
  Grid layout: grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 md:gap-8

  Pricing tables (when applicable):
  - Always 3 columns on desktop (grid-cols-1 md:grid-cols-3)
  - Middle column is "popular": scale-105, ring-2 ring-{{brand}}, badge "Popular" at top
  - Each card: rounded-2xl shadow-lg p-8, price in text-4xl font-bold, feature list with check icons
  - CTA button at bottom of each card

  Testimonials:
  <div class="bg-white rounded-2xl shadow-lg p-6 md:p-8">
    <div class="flex items-center gap-4 mb-4">
      <img src="https://picsum.photos/seed/person-NAME/80/80" class="w-12 h-12 rounded-full object-cover" alt="...">
      <div>
        <p class="font-semibold">Name</p>
        <p class="text-sm text-gray-500">Role / Company</p>
      </div>
    </div>
    <div class="flex gap-1 mb-3 text-yellow-400">★★★★★</div>
    <p class="text-gray-600 leading-relaxed italic">"Quote text..."</p>
  </div>

  Buttons:
  - Primary: px-6 py-3 md:px-8 md:py-4 bg-{{brand}} text-white rounded-xl font-semibold hover:bg-{{brand-dark}} transition-colors duration-200 shadow-lg hover:shadow-xl
  - Secondary/outline: px-6 py-3 border-2 border-{{brand}} text-{{brand}} rounded-xl font-semibold hover:bg-{{brand}} hover:text-white transition-colors duration-200

HERO SECTION PATTERN:
- Full viewport height: min-h-screen
- Use a layered approach: background image with dark overlay + centered content
  <section class="relative min-h-screen flex items-center justify-center overflow-hidden">
    <img src="https://picsum.photos/seed/SEED/1920/1080" class="absolute inset-0 w-full h-full object-cover" alt="...">
    <div class="absolute inset-0 bg-gradient-to-b from-black/60 via-black/40 to-black/70"></div>
    <div class="relative z-10 text-center text-white max-w-4xl mx-auto px-4">
      <h1 class="text-4xl md:text-5xl lg:text-6xl font-bold tracking-tight leading-tight mb-6">...</h1>
      <p class="text-lg md:text-xl text-white/90 mb-8 max-w-2xl mx-auto">...</p>
      <div class="flex flex-col sm:flex-row gap-4 justify-center">
        <!-- Primary + Secondary CTA buttons -->
      </div>
    </div>
  </section>

ANIMATION RULES (CRITICAL — content must NEVER be invisible):
- ALL content is visible by default. Animations are progressive enhancement ONLY.
- Use a single inline <script> at the end of <body> (before </body>) with IntersectionObserver.
- The script ADDS animation classes to elements, it does NOT start them hidden.
- Pattern:
  <script>
  document.addEventListener('DOMContentLoaded', function() {{
    const observer = new IntersectionObserver((entries) => {{
      entries.forEach(entry => {{
        if (entry.isIntersecting) {{
          entry.target.classList.add('animate-fade-in');
          observer.unobserve(entry.target);
        }}
      }});
    }}, {{ threshold: 0.1 }});
    document.querySelectorAll('[data-animate]').forEach(el => observer.observe(el));
  }});
  lucide.createIcons();
  </script>
- Add a <style> block for the animation:
  <style>
  @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
  .animate-fade-in {{ animation: fadeIn 0.6s ease-out forwards; }}
  </style>
- Mark sections with data-animate attribute. They remain fully visible (opacity:1) even without JS.
- Do NOT use opacity-0, translate-y-4, or any Tailwind class that hides content by default.
- Do NOT use Alpine x-intersect for animations.

FOOTER PATTERN:
<footer class="bg-gray-900 text-white py-12 md:py-16">
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
    <div class="grid grid-cols-1 md:grid-cols-4 gap-8">
      <!-- Column 1: Brand + description -->
      <div class="md:col-span-1">
        <h3 class="text-xl font-bold mb-4">Company Name</h3>
        <p class="text-gray-400 leading-relaxed">Short description.</p>
      </div>
      <!-- Column 2: Quick Links -->
      <div>
        <h4 class="font-semibold mb-4">Quick Links</h4>
        <ul class="space-y-2 text-gray-400">
          <li><a href="#section" class="hover:text-white transition-colors">Link</a></li>
          ...
        </ul>
      </div>
      <!-- Column 3: Contact info -->
      <div>
        <h4 class="font-semibold mb-4">Contact</h4>
        <ul class="space-y-2 text-gray-400">...</ul>
      </div>
      <!-- Column 4: Social icons -->
      <div>
        <h4 class="font-semibold mb-4">Follow Us</h4>
        <div class="flex gap-4">
          <a href="#" class="text-gray-400 hover:text-white transition-colors"><i data-lucide="instagram" class="w-5 h-5"></i></a>
          <a href="#" class="text-gray-400 hover:text-white transition-colors"><i data-lucide="twitter" class="w-5 h-5"></i></a>
          <a href="#" class="text-gray-400 hover:text-white transition-colors"><i data-lucide="facebook" class="w-5 h-5"></i></a>
        </div>
      </div>
    </div>
    <div class="border-t border-gray-800 mt-8 pt-8 text-center text-gray-500 text-sm">
      <p>&copy; 2025 Company Name. All rights reserved.</p>
      <p class="mt-2">Made with Wai ✨</p>
    </div>
  </div>
</footer>

REQUIREMENTS:
- Single HTML file, all content inline
- Hero section following the HERO SECTION PATTERN above
- At least 4 content sections (services/features, about, testimonials, contact)
- Follow all DESIGN SYSTEM rules for spacing, typography, and containers
- Follow all COMPONENT PATTERNS for cards, buttons, testimonials, etc.
- Follow ANIMATION RULES — content always visible, animations are additive only
- Follow FOOTER PATTERN with columns, links, social icons, and "Made with Wai ✨"
- Mobile-responsive: add `overflow-x: hidden` on <html> and <body>. Use `break-words` on headings. All text must fit within 375px viewport without horizontal scroll.
- If a THEME section is provided above, strictly follow its color scheme, fonts, and styling. Otherwise pick a professional color scheme fitting the business.
- End of <body> must include: <script>lucide.createIcons();</script> (inside the animation script or standalone)

OUTPUT: Only the HTML starting with <!DOCTYPE html>. No markdown, no explanation."""


@dataclass
class SiteResult:
    slug: str
    url: str
    path: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    success: bool = True
    error: str | None = None
    html: str | None = None


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


async def build_site(
    description: str, name: str | None = None, theme: str = "default"
) -> SiteResult:
    """Generate and deploy a website from a text description.

    Args:
        description: User's site description.
        name: Optional name for slug generation.
        theme: Theme key from THEMES dict (default lets Claude choose).

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

    # Build theme instructions for the prompt
    theme_instructions = get_theme_prompt(theme)
    if theme_instructions:
        theme_instructions = "\n" + theme_instructions + "\n"

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
                        description=description[:3000],
                        theme_instructions=theme_instructions,
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

        # Validate before deploy
        from app.services.agent.html_validator import validate_html

        is_valid, validation_error = validate_html(html, "site")
        if not is_valid:
            logger.error(f"Site validation failed: {validation_error}")
            return SiteResult(
                slug=slug,
                url="",
                path="",
                success=False,
                error=f"Quality check failed: {validation_error}",
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
            html=html,
        )
    else:
        return SiteResult(
            slug=slug,
            url="",
            path="",
            success=False,
            error=deploy_result.get("error", "Deploy failed"),
        )


def store_site(chat_id: int, slug: str, html: str) -> None:
    """Store last generated HTML for a chat in Redis (survives restarts)."""
    import json

    try:
        r = _get_redis()
        data = json.dumps({"slug": slug, "html": html})
        r.setex(f"site:{chat_id}", _SITE_STORE_TTL, data)
    except Exception as e:
        logger.warning(f"Failed to store site in Redis: {e}")


def get_stored_site(chat_id: int) -> tuple[str, str] | None:
    """Return (slug, html) for the last site built by this chat, or None."""
    import json

    try:
        r = _get_redis()
        data = r.get(f"site:{chat_id}")
        if data:
            parsed = json.loads(data)
            return (parsed["slug"], parsed["html"])
    except Exception as e:
        logger.warning(f"Failed to get site from Redis: {e}")
    return None


def track_deployed_site(
    chat_id: int, slug: str, url: str, content_type: str = "site"
) -> None:
    """Track a deployed site/slide/table/doc for /sites listing."""
    import json
    import time

    try:
        r = _get_redis()
        entry = json.dumps(
            {"slug": slug, "url": url, "type": content_type, "ts": int(time.time())}
        )
        r.lpush(f"deployed:{chat_id}", entry)
        r.ltrim(f"deployed:{chat_id}", 0, 49)  # Keep last 50
        r.expire(f"deployed:{chat_id}", _SITES_LIST_TTL)
    except Exception as e:
        logger.warning(f"Failed to track deployed site: {e}")


def get_deployed_sites(chat_id: int) -> list[dict]:
    """Get all deployed sites for a chat."""
    import json

    try:
        r = _get_redis()
        items = r.lrange(f"deployed:{chat_id}", 0, 49)
        return [json.loads(item) for item in items] if items else []
    except Exception as e:
        logger.warning(f"Failed to get deployed sites: {e}")
        return []


async def edit_site(chat_id: int, instruction: str) -> SiteResult:
    """Edit the last generated site for a chat and redeploy it.

    Fetches stored HTML, sends it to Claude with the edit instruction,
    then redeploys to the same slug.
    """
    stored = get_stored_site(chat_id)
    if stored is None:
        return SiteResult(
            slug="",
            url="",
            path="",
            success=False,
            error="no_previous_site",
        )

    slug, current_html = stored
    settings = get_settings()

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16384,
            messages=[
                {
                    "role": "user",
                    "content": (
                        SITE_EDIT_PROMPT.format(instruction=instruction)
                        + "\n\n"
                        + current_html
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

        # Extract HTML if wrapped in text
        if not html.startswith("<!DOCTYPE") and not html.startswith("<html"):
            match = re.search(
                r"(<!DOCTYPE html.*</html>)", html, re.DOTALL | re.IGNORECASE
            )
            if match:
                html = match.group(1)
            else:
                logger.error(f"Invalid HTML from edit (first 200 chars): {html[:200]}")
                return SiteResult(
                    slug=slug,
                    url="",
                    path="",
                    success=False,
                    error="Failed to generate valid HTML from edit",
                )

        # Validate before deploy
        from app.services.agent.html_validator import validate_html

        is_valid, validation_error = validate_html(html, "site")
        if not is_valid:
            logger.error(f"Edited site validation failed: {validation_error}")
            return SiteResult(
                slug=slug,
                url="",
                path="",
                success=False,
                error=f"Quality check failed: {validation_error}",
            )

    except Exception as e:
        logger.error(f"Site edit generation failed: {e}")
        return SiteResult(
            slug=slug,
            url="",
            path="",
            success=False,
            error=f"AI edit failed: {e}",
        )

    # Redeploy to the same slug
    from app.services.agent.cloudflare_deploy import deploy_site_to_pages

    deploy_result = await deploy_site_to_pages(slug, html)

    if deploy_result["success"]:
        # Update stored HTML
        store_site(chat_id, slug, html)
        url = deploy_result["url"]
        logger.info(f"Site edited and redeployed: {url}")
        return SiteResult(slug=slug, url=url, path=url)
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
