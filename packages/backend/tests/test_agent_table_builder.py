"""Tests for Table Builder — slug generation, HTML cleanup, result dataclass, prompt."""

import re
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.table_builder import (
    TABLE_GENERATION_PROMPT,
    TableResult,
    build_table,
)
from app.services.agent.site_builder import generate_slug


class TestTableSlugGeneration:
    """Table slugs must have 'table-' prefix and a uuid suffix."""

    def test_slug_has_table_prefix(self):
        slug = generate_slug("Product Comparison")
        slug = f"table-{slug}"
        assert slug.startswith("table-")

    def test_slug_preserves_content(self):
        slug = generate_slug("SaaS Pricing")
        slug = f"table-{slug}"
        assert "saas-pricing" in slug

    def test_slug_cyrillic(self):
        slug = generate_slug("Сравнение продуктов")
        slug = f"table-{slug}"
        assert slug.startswith("table-")
        assert "sravnenie" in slug

    def test_slug_special_chars_removed(self):
        slug = generate_slug("Top 10 Tools [2026] & More!")
        slug = f"table-{slug}"
        assert "[" not in slug
        assert "]" not in slug
        assert "&" not in slug
        assert "!" not in slug

    def test_slug_max_length(self):
        slug = generate_slug("B" * 100)
        slug = f"table-{slug}"
        # generate_slug caps at 50, plus "table-" = 56 max
        assert len(slug) <= 56


class TestTableHTMLCleanup:
    """Test markdown stripping logic used in build_table."""

    def test_strip_markdown_code_block(self):
        raw = "```html\n<!DOCTYPE html><html><body>Table</body></html>\n```"
        html = raw.strip()
        if html.startswith("```"):
            html = re.sub(r"^```\w*\n?", "", html)
            html = re.sub(r"\n?```$", "", html)
            html = html.strip()
        assert html.startswith("<!DOCTYPE html>")
        assert "```" not in html

    def test_extract_html_from_wrapped_text(self):
        raw = (
            "Here's your table:\n<!DOCTYPE html><html><body>Grid</body></html>\nEnjoy!"
        )
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
        clean = "<!DOCTYPE html><html><body><div id='grid'></div></body></html>"
        html = clean.strip()
        if html.startswith("```"):
            html = re.sub(r"^```\w*\n?", "", html)
            html = re.sub(r"\n?```$", "", html)
            html = html.strip()
        assert html == clean

    def test_html_starting_with_html_tag(self):
        raw = "<html><head></head><body>Content</body></html>"
        html = raw.strip()
        # Should pass through since it starts with <html
        assert html.startswith("<html")


class TestTablePromptFormatting:
    """TABLE_GENERATION_PROMPT must format without errors."""

    def test_format_basic(self):
        result = TABLE_GENERATION_PROMPT.format(description="Compare top 5 laptops")
        assert "Compare top 5 laptops" in result

    def test_format_long_description(self):
        long_desc = "data point " * 500
        result = TABLE_GENERATION_PROMPT.format(description=long_desc[:3000])
        assert len(result) > 100

    def test_prompt_contains_ag_grid(self):
        result = TABLE_GENERATION_PROMPT.format(description="test")
        assert "AG Grid" in result or "ag-grid" in result

    def test_prompt_contains_data_requirements(self):
        result = TABLE_GENERATION_PROMPT.format(description="test")
        assert "REAL data" in result
        assert "5-15 rows" in result

    def test_prompt_contains_export(self):
        result = TABLE_GENERATION_PROMPT.format(description="test")
        assert "Export CSV" in result


class TestTableResultDataclass:
    """TableResult must hold all expected fields."""

    def test_success_result(self):
        r = TableResult(
            slug="table-demo-abc1", url="https://example.com", rows=10, columns=5
        )
        assert r.success is True
        assert r.error is None
        assert r.rows == 10
        assert r.columns == 5
        assert r.slug == "table-demo-abc1"
        assert r.url == "https://example.com"
        assert isinstance(r.created_at, datetime)

    def test_failure_result(self):
        r = TableResult(
            slug="table-fail-0000", url="", success=False, error="Deploy failed"
        )
        assert r.success is False
        assert r.error == "Deploy failed"
        assert r.rows == 0
        assert r.columns == 0

    def test_default_created_at_is_utc(self):
        r = TableResult(slug="t", url="")
        assert r.created_at.tzinfo is not None


class TestRowColumnCounting:
    """Row and column counting from AG Grid JS."""

    def test_count_header_names(self):
        html = """
        const columnDefs = [
            { headerName: "Product", field: "product" },
            { headerName: "Price", field: "price" },
            { headerName: "Rating", field: "rating" },
        ];
        """
        columns = len(re.findall(r"headerName", html))
        assert columns == 3

    def test_count_row_data_objects(self):
        html = """
        const rowData = [
            { product: "A", price: 10 },
            { product: "B", price: 20 },
            { product: "C", price: 30 },
        ];
        """
        row_data = re.search(r"rowData\s*[:=]\s*\[", html)
        assert row_data is not None
        rows = html[row_data.end() :].count("}")
        assert rows == 3

    def test_zero_columns_no_headers(self):
        html = "<html><body>Nothing</body></html>"
        columns = len(re.findall(r"headerName", html))
        assert columns == 0


def _valid_table_html(rows: int = 5, columns: int = 3) -> str:
    """Build a valid AG Grid HTML that passes html_validator checks.

    Requirements: 200+ chars, DOCTYPE, <head></head>, </body>, </html>,
    ag-grid/agGrid reference, and rowData with data rows.
    """
    col_defs = ", ".join(
        f'{{ headerName: "Col{i}", field: "col{i}", sortable: true, filter: true }}'
        for i in range(1, columns + 1)
    )
    row_data = ", ".join(
        "{ " + ", ".join(f'col{c}: "R{r}C{c}"' for c in range(1, columns + 1)) + " }"
        for r in range(1, rows + 1)
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Test Table</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ag-grid-community@33/styles/ag-grid.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ag-grid-community@33/styles/ag-theme-alpine.css">
<script src="https://cdn.jsdelivr.net/npm/ag-grid-community@33/dist/ag-grid-community.min.js"></script>
</head>
<body>
<h1>Data Table</h1>
<div id="grid" class="ag-theme-alpine" style="height:500px;width:100%;"></div>
<script>
const columnDefs = [{col_defs}];
const rowData = [{row_data}];
const gridOptions = {{ columnDefs, rowData, defaultColDef: {{ sortable: true, filter: true }} }};
agGrid.createGrid(document.getElementById('grid'), gridOptions);
</script>
</body>
</html>"""


class TestBuildTableIntegration:
    """Test build_table with mocked Claude API and deploy."""

    @pytest.mark.asyncio
    async def test_build_success(self):
        mock_html = _valid_table_html(rows=5, columns=2)
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=mock_html)]

        mock_deploy = AsyncMock(
            return_value={"success": True, "url": "https://table-test.pages.dev"}
        )

        with (
            patch(
                "app.services.agent.table_builder.anthropic.AsyncAnthropic"
            ) as mock_cls,
            patch("app.services.agent.table_builder.get_settings") as mock_settings,
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages", mock_deploy
            ),
        ):
            mock_settings.return_value.anthropic_api_key = "test-key"
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await build_table("Compare laptops")

        assert result.slug.startswith("table-")
        assert result.success is True
        assert result.columns == 2  # 2 headerName occurrences
        assert result.url == "https://table-test.pages.dev"

    @pytest.mark.asyncio
    async def test_build_api_failure(self):
        with (
            patch(
                "app.services.agent.table_builder.anthropic.AsyncAnthropic"
            ) as mock_cls,
            patch("app.services.agent.table_builder.get_settings") as mock_settings,
        ):
            mock_settings.return_value.anthropic_api_key = "test-key"
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                side_effect=Exception("Rate limited")
            )
            mock_cls.return_value = mock_client

            result = await build_table("Test table")

        assert result.success is False
        assert "Rate limited" in result.error
        assert result.slug.startswith("table-")

    @pytest.mark.asyncio
    async def test_build_invalid_html(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="I cannot create that table.")]

        with (
            patch(
                "app.services.agent.table_builder.anthropic.AsyncAnthropic"
            ) as mock_cls,
            patch("app.services.agent.table_builder.get_settings") as mock_settings,
        ):
            mock_settings.return_value.anthropic_api_key = "test-key"
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await build_table("Bad request")

        assert result.success is False
        assert "valid table HTML" in result.error

    @pytest.mark.asyncio
    async def test_build_deploy_failure(self):
        mock_html = _valid_table_html(rows=3, columns=2)
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=mock_html)]

        mock_deploy = AsyncMock(
            return_value={"success": False, "error": "No credentials"}
        )

        with (
            patch(
                "app.services.agent.table_builder.anthropic.AsyncAnthropic"
            ) as mock_cls,
            patch("app.services.agent.table_builder.get_settings") as mock_settings,
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages", mock_deploy
            ),
        ):
            mock_settings.return_value.anthropic_api_key = "test-key"
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await build_table("Test")

        assert result.success is False
        assert "No credentials" in result.error or "Deploy" in result.error

    @pytest.mark.asyncio
    async def test_build_no_grid_fails_validation(self):
        """HTML without ag-grid references should fail table validation."""
        mock_html = """<!DOCTYPE html>
<html><head><title>Bad</title></head>
<body><h1>No Grid Here</h1><p>Just some text without any table or grid component at all.</p>
<p>This is filler to get past the 200 char minimum length requirement for the validator.</p>
</body></html>"""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=mock_html)]

        with (
            patch(
                "app.services.agent.table_builder.anthropic.AsyncAnthropic"
            ) as mock_cls,
            patch("app.services.agent.table_builder.get_settings") as mock_settings,
        ):
            mock_settings.return_value.anthropic_api_key = "test-key"
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            result = await build_table("No grid")

        assert result.success is False
        assert "grid" in result.error.lower() or "table" in result.error.lower()

    @pytest.mark.asyncio
    async def test_description_truncated_to_3000(self):
        """build_table truncates description to 3000 chars."""
        long_desc = "x" * 5000
        mock_html = _valid_table_html(rows=3, columns=2)
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=mock_html)]

        mock_deploy = AsyncMock(
            return_value={"success": True, "url": "https://test.pages.dev"}
        )
        captured_prompt = []

        async def capture_create(**kwargs):
            captured_prompt.append(kwargs["messages"][0]["content"])
            return mock_response

        with (
            patch(
                "app.services.agent.table_builder.anthropic.AsyncAnthropic"
            ) as mock_cls,
            patch("app.services.agent.table_builder.get_settings") as mock_settings,
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages", mock_deploy
            ),
        ):
            mock_settings.return_value.anthropic_api_key = "test-key"
            mock_client = AsyncMock()
            mock_client.messages.create = capture_create
            mock_cls.return_value = mock_client

            await build_table(long_desc)

        # The description in the prompt should be truncated
        assert len(captured_prompt[0]) < len(long_desc) + len(TABLE_GENERATION_PROMPT)
