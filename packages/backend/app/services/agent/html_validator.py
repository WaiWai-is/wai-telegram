"""HTML Validator — verify generated content before deploying to users.

Checks that generated output is a complete, renderable page.
Used by site_builder, presentation_builder, and table_builder.
"""

import logging
import re

logger = logging.getLogger(__name__)


def validate_html(html: str, content_type: str = "site") -> tuple[bool, str]:
    """Validate generated HTML before deployment.

    Returns (is_valid, error_message). If valid, error_message is empty.
    """
    if not html or len(html) < 200:
        return False, "Generated HTML is too short (likely incomplete)"

    # Must have DOCTYPE and closing html tag
    if "<!DOCTYPE" not in html and "<html" not in html:
        return False, "Missing DOCTYPE or <html> tag"

    if "</html>" not in html.lower():
        return False, "HTML is truncated (missing </html>)"

    if "</body>" not in html.lower():
        return False, "HTML is truncated (missing </body>)"

    if "<head" not in html.lower() or "</head>" not in html.lower():
        return False, "Missing <head> section"

    # Content-type specific checks
    if content_type == "site":
        return _validate_site(html)
    elif content_type == "presentation":
        return _validate_presentation(html)
    elif content_type == "table":
        return _validate_table(html)

    return True, ""


def _validate_site(html: str) -> tuple[bool, str]:
    """Validate a generated website."""
    # Must have visible body content (not just CSS)
    body_match = re.search(r"<body[^>]*>(.*)</body>", html, re.DOTALL | re.IGNORECASE)
    if not body_match:
        return False, "No <body> content found"

    body_content = body_match.group(1)

    # Strip script and style tags to check actual content
    text_content = re.sub(
        r"<script[^>]*>.*?</script>", "", body_content, flags=re.DOTALL | re.IGNORECASE
    )
    text_content = re.sub(
        r"<style[^>]*>.*?</style>", "", text_content, flags=re.DOTALL | re.IGNORECASE
    )
    text_content = re.sub(r"<[^>]+>", "", text_content)
    text_content = text_content.strip()

    if len(text_content) < 100:
        return False, "Page has almost no visible text content (CSS-only output)"

    # Should have at least some structural elements
    has_heading = bool(re.search(r"<h[1-6]", html, re.IGNORECASE))
    if not has_heading:
        return False, "No headings found — page structure is missing"

    return True, ""


def _validate_presentation(html: str) -> tuple[bool, str]:
    """Validate a generated reveal.js presentation."""
    if "reveal" not in html.lower():
        return False, "reveal.js not detected in presentation"

    section_count = len(re.findall(r"<section", html, re.IGNORECASE))
    if section_count < 3:
        return False, f"Only {section_count} slides found (minimum 3 required)"

    return True, ""


def _validate_table(html: str) -> tuple[bool, str]:
    """Validate a generated data table."""
    has_grid = "ag-grid" in html.lower() or "agGrid" in html or "ag-theme" in html
    has_table = "<table" in html.lower()

    if not has_grid and not has_table:
        return False, "No data grid or table element found"

    # Check for actual data
    has_data = "rowData" in html or "<tr" in html.lower()
    if not has_data:
        return False, "Table has no data rows"

    return True, ""
