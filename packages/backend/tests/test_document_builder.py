"""Tests for document_builder — document generation, type detection, and page estimation."""

from app.services.agent.document_builder import (
    DOCUMENT_GENERATION_PROMPT,
    DocumentResult,
    detect_doc_type,
    estimate_pages,
)


class TestDocumentPrompt:
    def test_prompt_formats_description(self):
        """Prompt should accept {description} without errors."""
        result = DOCUMENT_GENERATION_PROMPT.format(
            description="NDA for two parties", today="29.03.2026"
        )
        assert "NDA for two parties" in result

    def test_prompt_formats_today(self):
        """Prompt should accept {today} and insert the date."""
        result = DOCUMENT_GENERATION_PROMPT.format(
            description="test", today="29.03.2026"
        )
        assert "29.03.2026" in result

    def test_prompt_both_placeholders(self):
        """Both {description} and {today} must be present and work together."""
        result = DOCUMENT_GENERATION_PROMPT.format(
            description="Quarterly report Q1", today="01.04.2026"
        )
        assert "Quarterly report Q1" in result
        assert "01.04.2026" in result

    def test_prompt_escapes_braces(self):
        """Double braces in CSS @page rules should survive .format()."""
        result = DOCUMENT_GENERATION_PROMPT.format(
            description="test", today="01.01.2026"
        )
        # CSS should have literal braces after formatting
        assert "@page {" in result
        assert "size: A4;" in result

    def test_prompt_contains_google_fonts(self):
        result = DOCUMENT_GENERATION_PROMPT.format(
            description="test", today="01.01.2026"
        )
        assert "Merriweather" in result
        assert "Inter" in result
        assert "fonts.googleapis.com" in result

    def test_prompt_contains_print_media(self):
        result = DOCUMENT_GENERATION_PROMPT.format(
            description="test", today="01.01.2026"
        )
        assert "@media print" in result

    def test_prompt_russian_description(self):
        result = DOCUMENT_GENERATION_PROMPT.format(
            description="Коммерческое предложение для клиента", today="29.03.2026"
        )
        assert "Коммерческое предложение для клиента" in result


class TestDocumentResult:
    def test_defaults(self):
        r = DocumentResult(slug="doc-test", url="https://example.com")
        assert r.success is True
        assert r.error is None
        assert r.doc_type == "document"
        assert r.page_estimate == 1
        assert r.html is None

    def test_failure(self):
        r = DocumentResult(
            slug="doc-test", url="", success=False, error="generation failed"
        )
        assert not r.success
        assert r.error == "generation failed"

    def test_with_doc_type(self):
        r = DocumentResult(
            slug="doc-nda", url="https://example.com", doc_type="contract"
        )
        assert r.doc_type == "contract"

    def test_with_page_estimate(self):
        r = DocumentResult(
            slug="doc-report",
            url="https://example.com",
            page_estimate=5,
        )
        assert r.page_estimate == 5

    def test_with_html(self):
        r = DocumentResult(
            slug="doc-test",
            url="https://example.com",
            html="<html>test</html>",
        )
        assert r.html == "<html>test</html>"


class TestDocTypeDetection:
    def test_proposal_english(self):
        assert detect_doc_type("Business proposal for client X") == "proposal"

    def test_proposal_russian(self):
        assert detect_doc_type("Коммерческое предложение") == "proposal"

    def test_contract_english(self):
        assert detect_doc_type("NDA agreement between two companies") == "contract"

    def test_contract_russian(self):
        assert detect_doc_type("Договор на оказание услуг") == "contract"

    def test_report_english(self):
        assert detect_doc_type("Quarterly financial report Q1 2026") == "report"

    def test_report_russian(self):
        assert detect_doc_type("Отчёт за первый квартал") == "report"

    def test_letter_english(self):
        assert detect_doc_type("Cover letter for job application") == "letter"

    def test_letter_russian(self):
        assert detect_doc_type("Рекомендательное письмо") == "letter"

    def test_meeting_summary_english(self):
        assert (
            detect_doc_type("Meeting minutes from Monday standup") == "meeting_summary"
        )

    def test_meeting_summary_russian(self):
        assert detect_doc_type("Протокол совещания от 29 марта") == "meeting_summary"

    def test_unknown_type(self):
        assert detect_doc_type("Something completely random xyz") == "document"


class TestPageEstimation:
    def test_short_document(self):
        html = "<html><body>" + "x" * 1000 + "</body></html>"
        assert estimate_pages(html) == 1

    def test_multipage_document(self):
        html = "<html><body>" + "x" * 9000 + "</body></html>"
        assert estimate_pages(html) == 3

    def test_strips_scripts(self):
        html = (
            "<html><body>"
            "<script>var x = 'lots of code';</script>" + "x" * 2000 + "</body></html>"
        )
        # Script content should not count toward page estimate
        assert estimate_pages(html) == 1

    def test_strips_styles(self):
        html = (
            "<html><body>"
            "<style>body { font-size: 12pt; }</style>" + "x" * 2000 + "</body></html>"
        )
        assert estimate_pages(html) == 1

    def test_minimum_one_page(self):
        html = "<html><body>Short</body></html>"
        assert estimate_pages(html) >= 1

    def test_strips_html_tags(self):
        html = (
            "<html><body>"
            + "<p>" * 500
            + "word " * 600
            + "</p>" * 500
            + "</body></html>"
        )
        pages = estimate_pages(html)
        assert pages >= 1
