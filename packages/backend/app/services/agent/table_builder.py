"""Table Builder — generate interactive data tables from text descriptions.

Same pattern as site_builder: Claude generates HTML → deploy to Cloudflare Pages.
Uses AG Grid Community (CDN) for sortable, filterable, exportable tables.
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

TABLE_GENERATION_PROMPT = """Generate a premium interactive data table as a single HTML page.

Description: {description}

TECH STACK (use these CDNs in <head>):
- AG Grid Community:
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ag-grid-community@33/styles/ag-grid.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ag-grid-community@33/styles/ag-theme-alpine.css">
  <script src="https://cdn.jsdelivr.net/npm/ag-grid-community@33/dist/ag-grid-community.min.js"></script>
- Google Fonts: Inter for body, JetBrains Mono for numbers
- Tailwind CSS: <script src="https://cdn.tailwindcss.com"></script>

DATA REQUIREMENTS:
- Fill in REAL data based on your knowledge. No "TBD" or "N/A" unless genuinely unknown.
- Pricing: actual prices with currency symbols
- Ratings: numeric (4.5/5) or descriptive (Excellent/Good/Basic)
- Yes/no features: use checkmark and cross emoji
- 5-15 rows, 4-10 columns

AG GRID SETUP (in a <script> block):
- Define columnDefs array with field, headerName, sortable: true, filter: true
- Define rowData array with the actual data objects
- defaultColDef: sortable true, filter true, resizable true
- domLayout: 'autoHeight'
- Use agGrid.createGrid(document.getElementById('grid'), gridOptions)

PAGE LAYOUT:
- Clean header: bold title + subtitle with row/column count
- Search input above grid (use AG Grid quickFilterText on input event)
- Full-width grid container with ag-theme-alpine class
- "Export CSV" button: call gridApi.exportDataAsCsv()
- Footer: "Made with Wai" + current year
- Card-style container with shadow, subtle gradient background
- Mobile: horizontal scroll on grid container

LANGUAGE: Match the description language for all UI text.

OUTPUT: Only the HTML starting with <!DOCTYPE html>. No markdown, no explanation."""


@dataclass
class TableResult:
    slug: str
    url: str
    rows: int = 0
    columns: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    success: bool = True
    error: str | None = None


async def build_table(description: str, name: str | None = None) -> TableResult:
    """Generate and deploy an interactive data table."""
    settings = get_settings()

    slug = generate_slug(name or description[:30])
    slug = f"table-{slug}-{uuid4().hex[:4]}"

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16384,
            messages=[
                {
                    "role": "user",
                    "content": TABLE_GENERATION_PROMPT.format(
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
                logger.error(f"Invalid table HTML: {html[:200]}")
                return TableResult(
                    slug=slug,
                    url="",
                    success=False,
                    error="Failed to generate valid table HTML",
                )

        # Count rows and columns
        rows = len(re.findall(r"headerName", html))
        columns = rows  # headerName count = column count
        row_data = re.search(r"rowData\s*[:=]\s*\[", html)
        if row_data:
            # Count objects in rowData array
            rows = html[row_data.end() :].count("}")

    except Exception as e:
        logger.error(f"Table generation failed: {e}")
        return TableResult(
            slug=slug,
            url="",
            success=False,
            error=f"AI generation failed: {e}",
        )

    # Deploy
    from app.services.agent.cloudflare_deploy import deploy_site_to_pages

    deploy_result = await deploy_site_to_pages(slug, html)

    if deploy_result["success"]:
        url = deploy_result["url"]
        logger.info(f"Table deployed: {url} ({rows} rows x {columns} cols)")
        return TableResult(
            slug=slug,
            url=url,
            rows=rows,
            columns=columns,
        )
    else:
        return TableResult(
            slug=slug,
            url="",
            success=False,
            error=deploy_result.get("error", "Deploy failed"),
        )
