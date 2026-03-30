"""Tests for document_builder — document generation, type detection, and page estimation."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.document_builder import (
    DOCUMENT_GENERATION_PROMPT,
    DocumentResult,
    _DOC_STORE_TTL,
    build_document,
    detect_doc_type,
    edit_document,
    estimate_pages,
    get_stored_document,
    store_document,
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


# ---------------------------------------------------------------------------
# Shared constants for async tests
# ---------------------------------------------------------------------------

VALID_HTML = (
    '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="UTF-8">'
    "<title>Test Doc</title></head>\n<body>\n"
    "<h1>Project Proposal</h1>\n"
    "<p>" + "This is professional content for the document. " * 20 + "</p>\n"
    "<h2>Scope of Work</h2>\n"
    "<p>" + "Details about the project scope and deliverables. " * 15 + "</p>\n"
    "</body>\n</html>"
)

SHORT_INVALID_HTML = "<html><body>Hi</body></html>"


def _make_claude_response(text: str):
    """Build a mock Anthropic messages.create() return value."""
    block = SimpleNamespace(text=text)
    return SimpleNamespace(content=[block])


# ---------------------------------------------------------------------------
# _get_redis
# ---------------------------------------------------------------------------


class TestGetRedis:
    def test_returns_redis_client(self, fake_redis):
        """_get_redis() should lazily create and cache a Redis client."""
        import app.services.agent.document_builder as mod

        old = mod._redis_client
        try:
            mod._redis_client = None
            mock_redis_mod = MagicMock()
            mock_redis_mod.from_url.return_value = fake_redis
            with patch.dict("sys.modules", {"redis": mock_redis_mod}):
                client = mod._get_redis()
                assert client is fake_redis
                mock_redis_mod.from_url.assert_called_once()
        finally:
            mod._redis_client = old

    def test_caches_client_on_second_call(self, fake_redis):
        """Subsequent calls reuse the cached client."""
        import app.services.agent.document_builder as mod

        old = mod._redis_client
        try:
            mod._redis_client = fake_redis
            client = mod._get_redis()
            assert client is fake_redis
        finally:
            mod._redis_client = old


# ---------------------------------------------------------------------------
# store_document / get_stored_document
# ---------------------------------------------------------------------------


class TestStoreAndGetDocument:
    def test_store_and_retrieve(self, fake_redis):
        """Round-trip store then retrieve document."""
        with patch(
            "app.services.agent.document_builder._get_redis", return_value=fake_redis
        ):
            store_document(123, "doc-test-ab12", VALID_HTML)
            result = get_stored_document(123)
            assert result is not None
            slug, html = result
            assert slug == "doc-test-ab12"
            assert html == VALID_HTML

    def test_get_returns_none_when_empty(self, fake_redis):
        """get_stored_document returns None when nothing stored."""
        with patch(
            "app.services.agent.document_builder._get_redis", return_value=fake_redis
        ):
            assert get_stored_document(999) is None

    def test_store_uses_correct_key_and_ttl(self, fake_redis):
        """store_document should use 'doc:{chat_id}' key with 7-day TTL."""
        with patch(
            "app.services.agent.document_builder._get_redis", return_value=fake_redis
        ):
            store_document(42, "doc-slug", "<html></html>")
            raw = fake_redis.get("doc:42")
            assert raw is not None
            parsed = json.loads(raw)
            assert parsed["slug"] == "doc-slug"
            ttl = fake_redis.ttl("doc:42")
            assert ttl > 0
            assert ttl <= _DOC_STORE_TTL

    def test_store_handles_redis_error(self):
        """store_document should not raise on Redis failure."""
        bad_redis = MagicMock()
        bad_redis.setex.side_effect = ConnectionError("redis down")
        with patch(
            "app.services.agent.document_builder._get_redis", return_value=bad_redis
        ):
            # Should not raise
            store_document(1, "slug", "html")

    def test_get_handles_redis_error(self):
        """get_stored_document returns None on Redis failure."""
        bad_redis = MagicMock()
        bad_redis.get.side_effect = ConnectionError("redis down")
        with patch(
            "app.services.agent.document_builder._get_redis", return_value=bad_redis
        ):
            assert get_stored_document(1) is None

    def test_different_chats_isolated(self, fake_redis):
        """Documents from different chats don't collide."""
        with patch(
            "app.services.agent.document_builder._get_redis", return_value=fake_redis
        ):
            store_document(1, "slug-a", "<html>A</html>")
            store_document(2, "slug-b", "<html>B</html>")
            a = get_stored_document(1)
            b = get_stored_document(2)
            assert a[0] == "slug-a"
            assert b[0] == "slug-b"


# ---------------------------------------------------------------------------
# build_document
# ---------------------------------------------------------------------------


class TestBuildDocument:
    @pytest.fixture(autouse=True)
    def _patch_settings(self):
        with patch("app.services.agent.document_builder.get_settings") as mock_s:
            mock_s.return_value = SimpleNamespace(
                anthropic_api_key="test-key",
                redis_url="redis://localhost:6379",
            )
            yield

    async def test_success_path(self):
        """Happy path: Claude returns valid HTML, deploy succeeds."""
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_claude_response(VALID_HTML)

        with (
            patch(
                "app.services.agent.document_builder.anthropic.AsyncAnthropic",
                return_value=mock_client,
            ),
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
                new_callable=AsyncMock,
                return_value={"success": True, "url": "https://doc-test.wai.computer"},
            ) as mock_deploy,
        ):
            result = await build_document("Business proposal for ACME")

        assert result.success is True
        assert "wai.computer" in result.url
        assert result.doc_type == "proposal"
        assert result.page_estimate >= 1
        assert result.html == VALID_HTML
        assert result.slug.startswith("doc-")
        mock_deploy.assert_awaited_once()

    async def test_uses_name_for_slug_when_provided(self):
        """When name= is given, slug should be based on name."""
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_claude_response(VALID_HTML)

        with (
            patch(
                "app.services.agent.document_builder.anthropic.AsyncAnthropic",
                return_value=mock_client,
            ),
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
                new_callable=AsyncMock,
                return_value={"success": True, "url": "https://doc-nda.wai.computer"},
            ),
        ):
            result = await build_document("NDA between parties", name="NDA Contract")

        assert result.success is True
        assert "doc-" in result.slug

    async def test_claude_returns_markdown_wrapped_html(self):
        """Claude sometimes wraps HTML in ```html ... ``` — should be stripped."""
        wrapped = "```html\n" + VALID_HTML + "\n```"
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_claude_response(wrapped)

        with (
            patch(
                "app.services.agent.document_builder.anthropic.AsyncAnthropic",
                return_value=mock_client,
            ),
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
                new_callable=AsyncMock,
                return_value={"success": True, "url": "https://test.wai.computer"},
            ),
        ):
            result = await build_document("A report on testing")

        assert result.success is True
        assert result.html.startswith("<!DOCTYPE")

    async def test_claude_returns_html_embedded_in_text(self):
        """Claude sometimes wraps HTML in explanatory text — should extract."""
        text_wrapped = "Here is the document:\n\n" + VALID_HTML + "\n\nLet me know!"
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_claude_response(text_wrapped)

        with (
            patch(
                "app.services.agent.document_builder.anthropic.AsyncAnthropic",
                return_value=mock_client,
            ),
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
                new_callable=AsyncMock,
                return_value={"success": True, "url": "https://test.wai.computer"},
            ),
        ):
            result = await build_document("Write a letter")

        assert result.success is True

    async def test_invalid_html_no_doctype(self):
        """If Claude returns garbage with no extractable HTML, error."""
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_claude_response(
            "I cannot generate that document for you."
        )

        with patch(
            "app.services.agent.document_builder.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            result = await build_document("Make a contract")

        assert result.success is False
        assert "Failed to generate valid document HTML" in result.error

    async def test_html_validation_failure(self):
        """If html_validator rejects the HTML, return error."""
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_claude_response(VALID_HTML)

        with (
            patch(
                "app.services.agent.document_builder.anthropic.AsyncAnthropic",
                return_value=mock_client,
            ),
            patch(
                "app.services.agent.html_validator.validate_html",
                return_value=(False, "No headings found"),
            ),
        ):
            result = await build_document("A report")

        assert result.success is False
        assert "Quality check failed" in result.error

    async def test_claude_api_exception(self):
        """If Claude API raises, return structured error."""
        mock_client = AsyncMock()
        mock_client.messages.create.side_effect = RuntimeError("API timeout")

        with patch(
            "app.services.agent.document_builder.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            result = await build_document("A proposal")

        assert result.success is False
        assert "AI generation failed" in result.error
        assert "API timeout" in result.error

    async def test_deploy_failure(self):
        """If Cloudflare deploy fails, return error with deploy message."""
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_claude_response(VALID_HTML)

        with (
            patch(
                "app.services.agent.document_builder.anthropic.AsyncAnthropic",
                return_value=mock_client,
            ),
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
                new_callable=AsyncMock,
                return_value={"success": False, "error": "Rate limited"},
            ),
        ):
            result = await build_document("A proposal for testing")

        assert result.success is False
        assert result.error == "Rate limited"

    async def test_deploy_failure_without_error_key(self):
        """If deploy returns success=False without error key, use default."""
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_claude_response(VALID_HTML)

        with (
            patch(
                "app.services.agent.document_builder.anthropic.AsyncAnthropic",
                return_value=mock_client,
            ),
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
                new_callable=AsyncMock,
                return_value={"success": False},
            ),
        ):
            result = await build_document("A letter for client")

        assert result.success is False
        assert result.error == "Deploy failed"

    async def test_description_truncated_to_3000(self):
        """Very long descriptions should be truncated in the prompt."""
        long_desc = "x" * 5000
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_claude_response(VALID_HTML)

        with (
            patch(
                "app.services.agent.document_builder.anthropic.AsyncAnthropic",
                return_value=mock_client,
            ),
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
                new_callable=AsyncMock,
                return_value={"success": True, "url": "https://test.wai.computer"},
            ),
        ):
            result = await build_document(long_desc)

        # Verify Claude was called with truncated description
        call_args = mock_client.messages.create.call_args
        prompt_content = call_args.kwargs["messages"][0]["content"]
        # The original 5000-char string should have been sliced to 3000
        assert "x" * 3001 not in prompt_content
        assert result.success is True


# ---------------------------------------------------------------------------
# edit_document
# ---------------------------------------------------------------------------


class TestEditDocument:
    @pytest.fixture(autouse=True)
    def _patch_settings(self):
        with patch("app.services.agent.document_builder.get_settings") as mock_s:
            mock_s.return_value = SimpleNamespace(
                anthropic_api_key="test-key",
                redis_url="redis://localhost:6379",
            )
            yield

    async def test_no_previous_document(self):
        """edit_document returns error when no stored document exists."""
        with patch(
            "app.services.agent.document_builder.get_stored_document",
            return_value=None,
        ):
            result = await edit_document(123, "add a table of contents")

        assert result.success is False
        assert result.error == "no_previous_document"
        assert result.slug == ""

    async def test_success_path(self, fake_redis):
        """Happy path: edit + redeploy succeeds."""
        edited_html = VALID_HTML.replace("Project Proposal", "Updated Proposal")
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_claude_response(edited_html)

        with (
            patch(
                "app.services.agent.document_builder.get_stored_document",
                return_value=("doc-test-ab12", VALID_HTML),
            ),
            patch(
                "app.services.agent.document_builder.anthropic.AsyncAnthropic",
                return_value=mock_client,
            ),
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
                new_callable=AsyncMock,
                return_value={
                    "success": True,
                    "url": "https://doc-test-ab12.wai.computer",
                },
            ),
            patch("app.services.agent.document_builder.store_document") as mock_store,
        ):
            result = await edit_document(123, "change the title")

        assert result.success is True
        assert result.url == "https://doc-test-ab12.wai.computer"
        assert result.slug == "doc-test-ab12"
        assert result.page_estimate >= 1
        mock_store.assert_called_once_with(123, "doc-test-ab12", edited_html)

    async def test_edit_strips_markdown_wrapping(self, fake_redis):
        """Edited HTML wrapped in ``` should be stripped."""
        wrapped = "```html\n" + VALID_HTML + "\n```"
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_claude_response(wrapped)

        with (
            patch(
                "app.services.agent.document_builder.get_stored_document",
                return_value=("doc-slug", VALID_HTML),
            ),
            patch(
                "app.services.agent.document_builder.anthropic.AsyncAnthropic",
                return_value=mock_client,
            ),
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
                new_callable=AsyncMock,
                return_value={"success": True, "url": "https://doc-slug.wai.computer"},
            ),
            patch("app.services.agent.document_builder.store_document"),
        ):
            result = await edit_document(123, "fix formatting")

        assert result.success is True

    async def test_edit_extracts_html_from_text(self):
        """Edited HTML embedded in explanation text should be extracted."""
        text_wrapped = "Sure, here is the updated HTML:\n\n" + VALID_HTML
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_claude_response(text_wrapped)

        with (
            patch(
                "app.services.agent.document_builder.get_stored_document",
                return_value=("doc-slug", VALID_HTML),
            ),
            patch(
                "app.services.agent.document_builder.anthropic.AsyncAnthropic",
                return_value=mock_client,
            ),
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
                new_callable=AsyncMock,
                return_value={"success": True, "url": "https://doc-slug.wai.computer"},
            ),
            patch("app.services.agent.document_builder.store_document"),
        ):
            result = await edit_document(123, "add footer")

        assert result.success is True

    async def test_edit_invalid_html_output(self):
        """If edit returns no extractable HTML, return error."""
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_claude_response(
            "Sorry, I cannot do that edit."
        )

        with (
            patch(
                "app.services.agent.document_builder.get_stored_document",
                return_value=("doc-slug", VALID_HTML),
            ),
            patch(
                "app.services.agent.document_builder.anthropic.AsyncAnthropic",
                return_value=mock_client,
            ),
        ):
            result = await edit_document(123, "delete everything")

        assert result.success is False
        assert "Failed to generate valid HTML from edit" in result.error

    async def test_edit_validation_failure(self):
        """If validator rejects edited HTML, return error."""
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_claude_response(VALID_HTML)

        with (
            patch(
                "app.services.agent.document_builder.get_stored_document",
                return_value=("doc-slug", VALID_HTML),
            ),
            patch(
                "app.services.agent.document_builder.anthropic.AsyncAnthropic",
                return_value=mock_client,
            ),
            patch(
                "app.services.agent.html_validator.validate_html",
                return_value=(False, "Missing <head> section"),
            ),
        ):
            result = await edit_document(123, "remove the head")

        assert result.success is False
        assert "Quality check failed" in result.error

    async def test_edit_claude_api_exception(self):
        """If Claude API raises during edit, return structured error."""
        mock_client = AsyncMock()
        mock_client.messages.create.side_effect = RuntimeError("service unavailable")

        with (
            patch(
                "app.services.agent.document_builder.get_stored_document",
                return_value=("doc-slug", VALID_HTML),
            ),
            patch(
                "app.services.agent.document_builder.anthropic.AsyncAnthropic",
                return_value=mock_client,
            ),
        ):
            result = await edit_document(123, "add a table")

        assert result.success is False
        assert "AI edit failed" in result.error

    async def test_edit_deploy_failure(self):
        """If redeploy fails after edit, return deploy error."""
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_claude_response(VALID_HTML)

        with (
            patch(
                "app.services.agent.document_builder.get_stored_document",
                return_value=("doc-slug", VALID_HTML),
            ),
            patch(
                "app.services.agent.document_builder.anthropic.AsyncAnthropic",
                return_value=mock_client,
            ),
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
                new_callable=AsyncMock,
                return_value={"success": False, "error": "Wrangler error"},
            ),
        ):
            result = await edit_document(123, "change colors")

        assert result.success is False
        assert result.error == "Wrangler error"

    async def test_edit_deploy_failure_default_message(self):
        """If deploy returns no error key, use default message."""
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_claude_response(VALID_HTML)

        with (
            patch(
                "app.services.agent.document_builder.get_stored_document",
                return_value=("doc-slug", VALID_HTML),
            ),
            patch(
                "app.services.agent.document_builder.anthropic.AsyncAnthropic",
                return_value=mock_client,
            ),
            patch(
                "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
                new_callable=AsyncMock,
                return_value={"success": False},
            ),
        ):
            result = await edit_document(123, "change font")

        assert result.success is False
        assert result.error == "Deploy failed"
