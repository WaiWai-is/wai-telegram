"""Tests for the /edit site refinement flow."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent.site_builder import (
    edit_site,
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

# Use a simple dict as a mock Redis backend for tests
_mock_store: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _mock_redis():
    """Mock Redis calls with a simple dict store."""
    _mock_store.clear()

    def mock_store(chat_id, slug, html):
        import json

        _mock_store[f"site:{chat_id}"] = json.dumps({"slug": slug, "html": html})

    def mock_get(chat_id):
        import json

        data = _mock_store.get(f"site:{chat_id}")
        if data:
            parsed = json.loads(data)
            return (parsed["slug"], parsed["html"])
        return None

    with (
        patch(
            "app.services.agent.site_builder.store_site", side_effect=mock_store
        ) as _m_store,
        patch(
            "app.services.agent.site_builder.get_stored_site", side_effect=mock_get
        ) as _m_get,
    ):
        # Also patch at module level for direct calls in tests
        store_site.__wrapped__ = mock_store  # type: ignore
        yield mock_store, mock_get

    _mock_store.clear()


def test_store_and_get_site(_mock_redis):
    mock_store, mock_get = _mock_redis
    mock_store(123, "my-slug", SAMPLE_HTML)
    result = mock_get(123)
    assert result is not None
    slug, html = result
    assert slug == "my-slug"
    assert html == SAMPLE_HTML


def test_get_stored_site_returns_none_when_empty(_mock_redis):
    _, mock_get = _mock_redis
    assert mock_get(999) is None


@pytest.mark.asyncio
async def test_edit_site_no_previous_site():
    with patch("app.services.agent.site_builder.get_stored_site", return_value=None):
        result = await edit_site(chat_id=999, instruction="add testimonials")
    assert result.success is False
    assert result.error == "no_previous_site"


@pytest.mark.asyncio
async def test_edit_site_success():
    with (
        patch(
            "app.services.agent.site_builder.get_stored_site",
            return_value=("cafe-sunrise", SAMPLE_HTML),
        ),
        patch("app.services.agent.site_builder.store_site") as mock_store_fn,
        patch(
            "app.services.agent.site_builder.generate_text",
            new_callable=AsyncMock,
            return_value=EDITED_HTML,
        ),
        patch(
            "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
            new_callable=AsyncMock,
        ) as mock_deploy,
    ):
        mock_deploy.return_value = {
            "success": True,
            "url": "https://cafe-sunrise.wai.computer",
            "slug": "cafe-sunrise",
        }

        result = await edit_site(123, "add a testimonials section")

    assert result.success is True
    assert result.slug == "cafe-sunrise"
    assert result.url == "https://cafe-sunrise.wai.computer"
    mock_store_fn.assert_called_once()


@pytest.mark.asyncio
async def test_edit_site_deploy_failure():
    with (
        patch(
            "app.services.agent.site_builder.get_stored_site",
            return_value=("cafe-sunrise", SAMPLE_HTML),
        ),
        patch("app.services.agent.site_builder.store_site"),
        patch(
            "app.services.agent.site_builder.generate_text",
            new_callable=AsyncMock,
            return_value=EDITED_HTML,
        ),
        patch(
            "app.services.agent.cloudflare_deploy.deploy_site_to_pages",
            new_callable=AsyncMock,
        ) as mock_deploy,
    ):
        mock_deploy.return_value = {
            "success": False,
            "error": "Cloudflare credentials not configured",
        }

        result = await edit_site(123, "add a testimonials section")

    assert result.success is False
    assert "Cloudflare" in result.error


@pytest.mark.asyncio
async def test_edit_site_invalid_html_from_model():
    with (
        patch(
            "app.services.agent.site_builder.get_stored_site",
            return_value=("cafe-sunrise", SAMPLE_HTML),
        ),
        patch(
            "app.services.agent.site_builder.generate_text",
            new_callable=AsyncMock,
            return_value="I can't generate HTML right now, sorry.",
        ),
    ):
        result = await edit_site(123, "make it darker")

    assert result.success is False
    assert "valid HTML" in result.error
