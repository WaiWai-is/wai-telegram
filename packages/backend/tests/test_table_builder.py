"""Tests for table_builder — interactive table generation and validation."""

import pytest

from app.services.agent.table_builder import TableResult, TABLE_GENERATION_PROMPT
from app.services.agent.site_builder import generate_slug


class TestTablePrompt:
    def test_prompt_formats_correctly(self):
        result = TABLE_GENERATION_PROMPT.format(description="Compare 5 CRMs")
        assert "Compare 5 CRMs" in result
        assert "ag-grid" in result.lower() or "AG Grid" in result

    def test_prompt_russian(self):
        result = TABLE_GENERATION_PROMPT.format(description="Сравнение мессенджеров")
        assert "Сравнение мессенджеров" in result

    def test_prompt_contains_cdns(self):
        result = TABLE_GENERATION_PROMPT.format(description="test")
        assert "cdn.jsdelivr.net" in result
        assert "ag-grid" in result

    def test_prompt_mentions_csv_export(self):
        result = TABLE_GENERATION_PROMPT.format(description="test")
        assert "CSV" in result or "csv" in result


class TestTableResult:
    def test_defaults(self):
        r = TableResult(slug="test", url="https://example.com")
        assert r.success is True
        assert r.error is None
        assert r.rows == 0
        assert r.columns == 0

    def test_with_dimensions(self):
        r = TableResult(slug="test", url="https://example.com", rows=10, columns=5)
        assert r.rows == 10
        assert r.columns == 5

    def test_failure(self):
        r = TableResult(slug="test", url="", success=False, error="fail")
        assert not r.success


class TestTableSlug:
    def test_slug_prefix(self):
        """Table slugs should contain table-related text when built."""
        slug = generate_slug("Compare CRM systems")
        assert slug == "compare-crm-systems"

    def test_slug_with_numbers(self):
        slug = generate_slug("Top 10 languages 2026")
        assert "10" in slug
        assert "2026" in slug
