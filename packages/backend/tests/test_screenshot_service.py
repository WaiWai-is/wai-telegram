"""Tests for Screenshot Service — Microlink API integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.services.agent.screenshot_service import get_screenshot_url


class TestGetScreenshotUrl:
    async def test_returns_screenshot_url_on_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {
                "screenshot": {"url": "https://cdn.microlink.io/screenshot-abc123.jpeg"}
            },
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_screenshot_url("https://test-site.wai.computer")

        assert result == "https://cdn.microlink.io/screenshot-abc123.jpeg"
        mock_client.get.assert_called_once()
        call_kwargs = mock_client.get.call_args
        assert call_kwargs[1]["params"]["url"] == "https://test-site.wai.computer"
        assert call_kwargs[1]["params"]["screenshot"] == "true"

    async def test_returns_none_on_non_200(self):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_screenshot_url("https://test-site.wai.computer")

        assert result is None

    async def test_returns_none_on_missing_screenshot_data(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success", "data": {}}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_screenshot_url("https://test-site.wai.computer")

        assert result is None

    async def test_returns_none_on_empty_screenshot_url(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {"screenshot": {"url": ""}},
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_screenshot_url("https://test-site.wai.computer")

        assert result is None

    async def test_returns_none_on_timeout(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_screenshot_url("https://test-site.wai.computer")

        assert result is None

    async def test_returns_none_on_connection_error(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_screenshot_url("https://test-site.wai.computer")

        assert result is None

    async def test_returns_none_on_json_decode_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("invalid json")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_screenshot_url("https://test-site.wai.computer")

        assert result is None

    async def test_passes_correct_viewport_params(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"screenshot": {"url": "https://cdn.microlink.io/img.jpeg"}}
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await get_screenshot_url("https://example.com")

        params = mock_client.get.call_args[1]["params"]
        assert params["viewport.width"] == "1280"
        assert params["viewport.height"] == "720"
        assert "embed" not in params

    async def test_returns_none_on_partial_data_structure(self):
        """Microlink returns data but no screenshot key at all."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {"title": "Some Page"},
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await get_screenshot_url("https://test-site.wai.computer")

        assert result is None
