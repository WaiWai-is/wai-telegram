"""Tests for the /edit site refinement flow."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent.site_builder import (
    _site_store,
    edit_site,
    get_stored_site,
    store_site,
)

SAMPLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Test</title></head>
<body>
<h1>Hello World</h1>
<p>This is a sample site with enough text content to pass the validator.
It has multiple paragraphs and sections to make it realistic enough for testing purposes.</p>
<h2>About Us</h2>
<p>We are a test company that does testing things. Our mission is to test everything thoroughly.</p>
</body>
</html>"""

EDITED_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Test Edited</title></head>
<body>
<h1>Hello World</h1>
<p>This is a sample site with enough text content to pass the validator.
It has multiple paragraphs and sections to make it realistic enough for testing purposes.</p>
<h2>About Us</h2>
<p>We are a test company that does testing things. Our mission is to test everything thoroughly.</p>
<section><h2>Testimonials</h2><p>Great service! Wonderful experience from our valued customers.</p></section>
</body>
</html>"""


@pytest.fixture(autouse=True)
def _clear_store():
    """Clear the in-memory site store between tests."""
    _site_store.clear()
    yield
    _site_store.clear()


def test_store_and_get_site():
    store_site(123, "my-slug", SAMPLE_HTML)
    result = get_stored_site(123)
    assert result is not None
    slug, html = result
    assert slug == "my-slug"
    assert html == SAMPLE_HTML


def test_get_stored_site_returns_none_when_empty():
    assert get_stored_site(999) is None


@pytest.mark.asyncio
async def test_edit_site_no_previous_site():
    result = await edit_site(chat_id=999, instruction="add testimonials")
    assert result.success is False
    assert result.error == "no_previous_site"


@pytest.mark.asyncio
async def test_edit_site_success():
    store_site(123, "cafe-sunrise", SAMPLE_HTML)

    mock_response = AsyncMock()
    mock_response.content = [AsyncMock(text=EDITED_HTML)]

    with (
        patch("app.services.agent.site_builder.anthropic.AsyncAnthropic") as mock_cls,
        patch(
            "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
            new_callable=AsyncMock,
        ) as mock_deploy,
    ):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client
        mock_deploy.return_value = {
            "success": True,
            "url": "https://cafe-sunrise.wai.computer",
            "slug": "cafe-sunrise",
        }

        result = await edit_site(123, "add a testimonials section")

    assert result.success is True
    assert result.slug == "cafe-sunrise"
    assert result.url == "https://cafe-sunrise.wai.computer"

    # Verify stored HTML was updated
    stored = get_stored_site(123)
    assert stored is not None
    assert "Testimonials" in stored[1]


@pytest.mark.asyncio
async def test_edit_site_deploy_failure():
    store_site(123, "cafe-sunrise", SAMPLE_HTML)

    mock_response = AsyncMock()
    mock_response.content = [AsyncMock(text=EDITED_HTML)]

    with (
        patch("app.services.agent.site_builder.anthropic.AsyncAnthropic") as mock_cls,
        patch(
            "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
            new_callable=AsyncMock,
        ) as mock_deploy,
    ):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client
        mock_deploy.return_value = {
            "success": False,
            "error": "Cloudflare credentials not configured",
        }

        result = await edit_site(123, "add a testimonials section")

    assert result.success is False
    assert "Cloudflare" in result.error

    # Stored HTML should NOT be updated on deploy failure
    stored = get_stored_site(123)
    assert stored is not None
    assert "Testimonials" not in stored[1]


@pytest.mark.asyncio
async def test_edit_site_invalid_html_from_claude():
    store_site(123, "cafe-sunrise", SAMPLE_HTML)

    mock_response = AsyncMock()
    mock_response.content = [AsyncMock(text="I can't generate HTML right now, sorry.")]

    with patch("app.services.agent.site_builder.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        result = await edit_site(123, "make it darker")

    assert result.success is False
    assert "valid HTML" in result.error


@pytest.mark.asyncio
async def test_edit_preserves_slug_across_edits():
    """Ensure multiple edits keep reusing the same slug."""
    store_site(123, "my-site", SAMPLE_HTML)

    mock_response = AsyncMock()
    mock_response.content = [AsyncMock(text=EDITED_HTML)]

    with (
        patch("app.services.agent.site_builder.anthropic.AsyncAnthropic") as mock_cls,
        patch(
            "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
            new_callable=AsyncMock,
        ) as mock_deploy,
    ):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client
        mock_deploy.return_value = {
            "success": True,
            "url": "https://my-site.wai.computer",
            "slug": "my-site",
        }

        result = await edit_site(123, "first edit")
        assert result.slug == "my-site"

        # Second edit should still use the same slug
        result2 = await edit_site(123, "second edit")
        assert result2.slug == "my-site"

        # Both deploy calls should use the same slug
        assert mock_deploy.call_count == 2
        for call in mock_deploy.call_args_list:
            assert call[0][0] == "my-site"
