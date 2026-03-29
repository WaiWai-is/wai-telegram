"""Document Builder — generate professional print-ready documents from text descriptions.

Same pattern as site_builder: Claude generates HTML → deploy to Cloudflare Pages.
Uses Google Fonts (Merriweather serif for body, Inter for headings) with print-optimized CSS.
Document types: proposals, contracts, reports, letters, meeting summaries.
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

_redis_client = None
_DOC_STORE_TTL = 86400 * 7


def _get_redis():
    """Get Redis client for document store (survives server restarts)."""
    global _redis_client
    if _redis_client is None:
        import redis

        _redis_client = redis.from_url(get_settings().redis_url)
    return _redis_client


DOCUMENT_EDIT_PROMPT = (
    "Here is the current HTML of a document. Apply the following changes: {instruction}. "
    "Return the COMPLETE updated HTML. Do not explain, just output the full HTML "
    "starting with <!DOCTYPE html>."
)

DOCUMENT_GENERATION_PROMPT = """Generate a professional, print-ready document as a single HTML file.

Description: {description}
Today's date: {today}

GOOGLE FONTS (include in <head>):
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Merriweather:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">

TYPOGRAPHY:
- Body text: Merriweather (serif), 12pt, line-height 1.8, color #1a1a1a
- Headings: Inter (sans-serif), bold, color #111
- H1: 24pt, H2: 18pt, H3: 14pt
- Monospace/code: 'Courier New', monospace

PAGE SETUP (CSS):
<style>
  @page {{
    size: A4;
    margin: 25mm 20mm 25mm 20mm;
  }}
  @media print {{
    body {{
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .no-print {{
      display: none !important;
    }}
    a {{
      text-decoration: none;
      color: inherit;
    }}
  }}
  body {{
    max-width: 210mm;
    margin: 0 auto;
    padding: 25mm 20mm;
    font-family: 'Merriweather', Georgia, serif;
    font-size: 12pt;
    line-height: 1.8;
    color: #1a1a1a;
    background: #fff;
  }}
  h1, h2, h3, h4, h5, h6 {{
    font-family: 'Inter', 'Helvetica Neue', sans-serif;
    color: #111;
    margin-top: 1.5em;
    margin-bottom: 0.5em;
    page-break-after: avoid;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 1em 0;
    page-break-inside: avoid;
  }}
  th, td {{
    border: 1px solid #ddd;
    padding: 8px 12px;
    text-align: left;
    font-size: 11pt;
  }}
  th {{
    background: #f5f5f5;
    font-family: 'Inter', sans-serif;
    font-weight: 600;
  }}
  blockquote {{
    border-left: 3px solid #333;
    margin: 1em 0;
    padding: 0.5em 1em;
    color: #444;
    font-style: italic;
  }}
  .page-break {{
    page-break-before: always;
  }}
  .signature-line {{
    border-top: 1px solid #333;
    width: 200px;
    margin-top: 40px;
    padding-top: 5px;
    font-family: 'Inter', sans-serif;
    font-size: 10pt;
  }}
</style>

DOCUMENT TYPES — detect from description and structure accordingly:
- **Proposal**: title page, executive summary, scope, timeline, pricing table, terms, signature block
- **Contract**: parties, recitals, numbered clauses, signatures with date lines
- **Report**: title, table of contents, executive summary, sections with data, conclusion
- **Letter**: sender info top-right, date, recipient, salutation, body, closing, signature
- **Meeting summary**: date, attendees, agenda items, decisions, action items table

REQUIREMENTS:
- Use today's date ({today}) wherever dates appear
- Professional tone, clean formatting
- Include page numbers via CSS: @bottom-center {{ content: "Page " counter(page) " of " counter(pages); }}
- Add a subtle header or footer with document title
- Tables for any structured data (pricing, timelines, action items)
- Signature lines where appropriate
- A small "Print" button (class="no-print") that calls window.print()

OUTPUT: Only the HTML starting with <!DOCTYPE html>. No markdown wrapping."""


DOC_TYPE_PATTERNS: dict[str, list[str]] = {
    "proposal": ["proposal", "предложение", "коммерческое", "bid", "pitch"],
    "contract": ["contract", "agreement", "договор", "контракт", "nda", "terms"],
    "report": ["report", "отчёт", "отчет", "analysis", "анализ", "review", "обзор"],
    "letter": ["letter", "письмо", "cover letter", "recommendation", "рекомендация"],
    "meeting_summary": [
        "meeting",
        "совещание",
        "встреча",
        "minutes",
        "протокол",
        "summary",
        "итоги",
    ],
}


def detect_doc_type(description: str) -> str:
    """Detect document type from description text."""
    desc_lower = description.lower()
    for doc_type, keywords in DOC_TYPE_PATTERNS.items():
        for keyword in keywords:
            # Use word boundary check to avoid false matches (e.g. "nda" in "monday")
            if re.search(r"\b" + re.escape(keyword) + r"\b", desc_lower):
                return doc_type
    return "document"


def estimate_pages(html: str) -> int:
    """Estimate page count from HTML content.

    Rough heuristic: ~3000 characters of visible text per A4 page.
    """
    # Strip tags to get visible text
    text = re.sub(
        r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.strip()
    char_count = len(text)
    pages = max(1, (char_count + 2999) // 3000)
    return pages


@dataclass
class DocumentResult:
    slug: str
    url: str
    doc_type: str = "document"
    page_estimate: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    success: bool = True
    error: str | None = None
    html: str | None = None


async def build_document(description: str, name: str | None = None) -> DocumentResult:
    """Generate and deploy a professional document."""
    settings = get_settings()

    slug = generate_slug(name or description[:30])
    slug = f"doc-{slug}"

    # Deduplicate
    slug = f"{slug}-{uuid4().hex[:4]}"

    doc_type = detect_doc_type(description)
    today = datetime.now(UTC).strftime("%d.%m.%Y")

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16384,
            messages=[
                {
                    "role": "user",
                    "content": DOCUMENT_GENERATION_PROMPT.format(
                        description=description[:3000],
                        today=today,
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
                return DocumentResult(
                    slug=slug,
                    url="",
                    doc_type=doc_type,
                    success=False,
                    error="Failed to generate valid document HTML",
                )

        # Validate before deploy (documents have headings and body text like sites)
        from app.services.agent.html_validator import validate_html

        is_valid, validation_error = validate_html(html, "site")
        if not is_valid:
            logger.error(f"Document validation failed: {validation_error}")
            return DocumentResult(
                slug=slug,
                url="",
                doc_type=doc_type,
                success=False,
                error=f"Quality check failed: {validation_error}",
            )

        # Estimate page count
        page_estimate = estimate_pages(html)

    except Exception as e:
        logger.error(f"Document generation failed: {e}")
        return DocumentResult(
            slug=slug,
            url="",
            doc_type=doc_type,
            success=False,
            error=f"AI generation failed: {e}",
        )

    # Deploy to Cloudflare Pages
    from app.services.agent.cloudflare_deploy import deploy_site_to_pages

    deploy_result = await deploy_site_to_pages(slug, html)

    if deploy_result["success"]:
        url = deploy_result["url"]
        logger.info(f"Document deployed: {url} ({doc_type}, ~{page_estimate} pages)")
        return DocumentResult(
            slug=slug,
            url=url,
            doc_type=doc_type,
            page_estimate=page_estimate,
            html=html,
        )
    else:
        return DocumentResult(
            slug=slug,
            url="",
            doc_type=doc_type,
            success=False,
            error=deploy_result.get("error", "Deploy failed"),
        )


def store_document(chat_id: int, slug: str, html: str) -> None:
    """Store last generated HTML for a chat in Redis."""
    import json

    try:
        r = _get_redis()
        data = json.dumps({"slug": slug, "html": html})
        r.setex(f"doc:{chat_id}", _DOC_STORE_TTL, data)
    except Exception as e:
        logger.warning(f"Failed to store document in Redis: {e}")


def get_stored_document(chat_id: int) -> tuple[str, str] | None:
    """Return (slug, html) for the last document built by this chat, or None."""
    import json

    try:
        r = _get_redis()
        data = r.get(f"doc:{chat_id}")
        if data:
            parsed = json.loads(data)
            return (parsed["slug"], parsed["html"])
    except Exception as e:
        logger.warning(f"Failed to get document from Redis: {e}")
    return None


async def edit_document(chat_id: int, instruction: str) -> DocumentResult:
    """Edit the last generated document for a chat and redeploy it."""
    stored = get_stored_document(chat_id)
    if stored is None:
        return DocumentResult(
            slug="",
            url="",
            success=False,
            error="no_previous_document",
        )

    slug, current_html = stored
    settings = get_settings()
    doc_type = detect_doc_type(instruction)

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16384,
            messages=[
                {
                    "role": "user",
                    "content": (
                        DOCUMENT_EDIT_PROMPT.format(instruction=instruction)
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
                logger.error(f"Invalid HTML from edit: {html[:200]}")
                return DocumentResult(
                    slug=slug,
                    url="",
                    success=False,
                    error="Failed to generate valid HTML from edit",
                )

        # Validate before deploy
        from app.services.agent.html_validator import validate_html

        is_valid, validation_error = validate_html(html, "site")
        if not is_valid:
            logger.error(f"Edited document validation failed: {validation_error}")
            return DocumentResult(
                slug=slug,
                url="",
                success=False,
                error=f"Quality check failed: {validation_error}",
            )

    except Exception as e:
        logger.error(f"Document edit generation failed: {e}")
        return DocumentResult(
            slug=slug,
            url="",
            success=False,
            error=f"AI edit failed: {e}",
        )

    # Redeploy to the same slug
    from app.services.agent.cloudflare_deploy import deploy_site_to_pages

    deploy_result = await deploy_site_to_pages(slug, html)

    if deploy_result["success"]:
        # Update stored HTML
        store_document(chat_id, slug, html)
        url = deploy_result["url"]
        page_estimate = estimate_pages(html)
        logger.info(f"Document edited and redeployed: {url}")
        return DocumentResult(
            slug=slug,
            url=url,
            doc_type=doc_type,
            page_estimate=page_estimate,
        )
    else:
        return DocumentResult(
            slug=slug,
            url="",
            success=False,
            error=deploy_result.get("error", "Deploy failed"),
        )
