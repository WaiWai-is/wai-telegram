"""Tests for document generation, validation, storage, editing, and deployment."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.document_builder import (
    DOCUMENT_GENERATION_PROMPT,
    DocumentResult,
    build_document,
    detect_doc_type,
    edit_document,
    estimate_pages,
    get_stored_document,
    store_document,
)


VALID_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Proposal</title></head>
<body><main><h1>Project Proposal</h1><h2>Scope</h2>
<p>This professional proposal describes the project scope, timeline, deliverables,
responsibilities, commercial terms, and the concrete next steps for both parties.</p>
</main></body></html>"""


def test_prompt_formats_dynamic_values_and_print_css():
    prompt = DOCUMENT_GENERATION_PROMPT.format(
        description="Коммерческое предложение", today="03.08.2026"
    )
    assert "Коммерческое предложение" in prompt
    assert "03.08.2026" in prompt
    assert "@page {" in prompt
    assert "@media print" in prompt


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Business proposal", "proposal"),
        ("Договор на оказание услуг", "contract"),
        ("Quarterly report", "report"),
        ("Рекомендательное письмо", "letter"),
        ("Meeting minutes", "meeting_summary"),
        ("Something else", "document"),
    ],
)
def test_detect_document_type(description, expected):
    assert detect_doc_type(description) == expected


def test_page_estimation_uses_visible_text_only():
    assert estimate_pages("<html><body>Short</body></html>") == 1
    assert estimate_pages("<html><body>" + "x" * 9000 + "</body></html>") == 3
    with_script = "<script>" + "x" * 9000 + "</script>" + "y" * 100
    assert estimate_pages(f"<html><body>{with_script}</body></html>") == 1


def test_document_result_defaults():
    result = DocumentResult(slug="doc-test", url="https://example.com")
    assert result.success is True
    assert result.doc_type == "document"
    assert result.page_estimate == 1
    assert result.error is None


def test_document_storage_is_isolated_by_chat():
    values: dict[str, str] = {}
    redis = MagicMock()
    redis.setex.side_effect = lambda key, _ttl, value: values.__setitem__(key, value)
    redis.get.side_effect = values.get
    with patch("app.services.agent.document_builder._get_redis", return_value=redis):
        store_document(1, "slug-a", "<html>A</html>")
        store_document(2, "slug-b", "<html>B</html>")
        assert get_stored_document(1) == ("slug-a", "<html>A</html>")
        assert get_stored_document(2) == ("slug-b", "<html>B</html>")


@pytest.mark.asyncio
async def test_build_document_uses_quality_luna_profile_and_deploys():
    generation = AsyncMock(return_value=VALID_HTML)
    with (
        patch("app.services.agent.document_builder.generate_text", generation),
        patch(
            "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
            new_callable=AsyncMock,
            return_value={"success": True, "url": "https://doc.wai.computer"},
        ) as deploy,
    ):
        result = await build_document("Business proposal for ACME", name="ACME")

    assert result.success is True
    assert result.doc_type == "proposal"
    assert result.slug.startswith("doc-acme-")
    assert result.html == VALID_HTML
    assert generation.await_args.kwargs == {
        "max_output_tokens": 16384,
        "quality": True,
    }
    deploy.assert_awaited_once_with(result.slug, VALID_HTML)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_output",
    [
        "```html\n" + VALID_HTML + "\n```",
        "Here is the document:\n" + VALID_HTML + "\nDone.",
    ],
)
async def test_build_document_normalizes_wrapped_html(model_output):
    with (
        patch(
            "app.services.agent.document_builder.generate_text",
            new_callable=AsyncMock,
            return_value=model_output,
        ),
        patch(
            "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
            new_callable=AsyncMock,
            return_value={"success": True, "url": "https://doc.wai.computer"},
        ),
    ):
        result = await build_document("A report")
    assert result.success is True
    assert result.html == VALID_HTML


@pytest.mark.asyncio
async def test_build_document_truncates_description():
    generation = AsyncMock(return_value=VALID_HTML)
    with (
        patch("app.services.agent.document_builder.generate_text", generation),
        patch(
            "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
            new_callable=AsyncMock,
            return_value={"success": True, "url": "https://doc.wai.computer"},
        ),
    ):
        await build_document("x" * 5000)
    prompt = generation.await_args.args[0]
    assert "x" * 3000 in prompt
    assert "x" * 3001 not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output", "validator", "error"),
    [
        ("not html", None, "valid document HTML"),
        (VALID_HTML, (False, "No headings"), "Quality check failed"),
    ],
)
async def test_build_document_rejects_invalid_output(output, validator, error):
    patches = [
        patch(
            "app.services.agent.document_builder.generate_text",
            new_callable=AsyncMock,
            return_value=output,
        )
    ]
    if validator is not None:
        patches.append(
            patch(
                "app.services.agent.html_validator.validate_html",
                return_value=validator,
            )
        )
    with patches[0]:
        if len(patches) == 2:
            with patches[1]:
                result = await build_document("test")
        else:
            result = await build_document("test")
    assert result.success is False
    assert error in result.error


@pytest.mark.asyncio
async def test_build_document_surfaces_generation_and_deploy_errors():
    with patch(
        "app.services.agent.document_builder.generate_text",
        new_callable=AsyncMock,
        side_effect=RuntimeError("provider timeout"),
    ):
        failed = await build_document("test")
    assert failed.success is False
    assert "provider timeout" in failed.error

    with (
        patch(
            "app.services.agent.document_builder.generate_text",
            new_callable=AsyncMock,
            return_value=VALID_HTML,
        ),
        patch(
            "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
            new_callable=AsyncMock,
            return_value={"success": False, "error": "Rate limited"},
        ),
    ):
        failed = await build_document("test")
    assert failed.error == "Rate limited"


@pytest.mark.asyncio
async def test_edit_document_requires_previous_document():
    with patch(
        "app.services.agent.document_builder.get_stored_document", return_value=None
    ):
        result = await edit_document(123, "add a table")
    assert result.success is False
    assert result.error == "no_previous_document"


@pytest.mark.asyncio
async def test_edit_document_uses_quality_profile_redeploys_and_stores():
    edited = VALID_HTML.replace("Project Proposal", "Updated Proposal")
    generation = AsyncMock(return_value=edited)
    with (
        patch(
            "app.services.agent.document_builder.get_stored_document",
            return_value=("doc-test", VALID_HTML),
        ),
        patch("app.services.agent.document_builder.generate_text", generation),
        patch(
            "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
            new_callable=AsyncMock,
            return_value={"success": True, "url": "https://doc.wai.computer"},
        ),
        patch("app.services.agent.document_builder.store_document") as store,
    ):
        result = await edit_document(123, "change the title")

    assert result.success is True
    assert generation.await_args.kwargs["quality"] is True
    assert VALID_HTML in generation.await_args.args[0]
    store.assert_called_once_with(123, "doc-test", edited)


@pytest.mark.asyncio
async def test_edit_document_reports_invalid_generation_and_deploy_failure():
    with (
        patch(
            "app.services.agent.document_builder.get_stored_document",
            return_value=("doc-test", VALID_HTML),
        ),
        patch(
            "app.services.agent.document_builder.generate_text",
            new_callable=AsyncMock,
            return_value="not html",
        ),
    ):
        invalid = await edit_document(123, "break it")
    assert "valid HTML" in invalid.error

    with (
        patch(
            "app.services.agent.document_builder.get_stored_document",
            return_value=("doc-test", VALID_HTML),
        ),
        patch(
            "app.services.agent.document_builder.generate_text",
            new_callable=AsyncMock,
            return_value=VALID_HTML,
        ),
        patch(
            "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
            new_callable=AsyncMock,
            return_value={"success": False, "error": "Wrangler error"},
        ),
    ):
        failed = await edit_document(123, "change colors")
    assert failed.error == "Wrangler error"
