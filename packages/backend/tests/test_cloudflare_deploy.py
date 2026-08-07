"""Tests for Cloudflare Pages deployment via wrangler CLI."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent.cloudflare_deploy import (
    deploy_to_cloudflare_pages,
    deploy_site_to_pages,
)


class TestDeployToCloudflarePages:
    @pytest.mark.asyncio
    async def test_returns_error_without_credentials(self):
        with patch.dict(
            "os.environ", {"CLOUDFLARE_API_TOKEN": "", "CLOUDFLARE_ACCOUNT_ID": ""}
        ):
            result = await deploy_to_cloudflare_pages("test-slug", "<html>test</html>")
        assert not result["success"]
        assert "credentials" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_success_extracts_url(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(
                b"Uploading... (1/1)\nDeployment complete! Take a peek over at https://abc123.wai-sites.pages.dev\n",
                b"",
            )
        )

        with (
            patch.dict(
                "os.environ",
                {
                    "CLOUDFLARE_API_TOKEN": "test-token",
                    "CLOUDFLARE_ACCOUNT_ID": "test-id",
                },
            ),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            result = await deploy_to_cloudflare_pages("test-slug", "<html>test</html>")

        assert result["success"]
        assert "abc123.wai-sites.pages.dev" in result["url"]
        assert result["slug"] == "test-slug"

    @pytest.mark.asyncio
    async def test_wrangler_failure(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(
            return_value=(b"", b"Error: authentication failed")
        )

        with (
            patch.dict(
                "os.environ",
                {
                    "CLOUDFLARE_API_TOKEN": "test-token",
                    "CLOUDFLARE_ACCOUNT_ID": "test-id",
                },
            ),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            result = await deploy_to_cloudflare_pages("test-slug", "<html>test</html>")

        assert not result["success"]
        assert "error" in result["error"].lower() or "Wrangler" in result["error"]


class TestDeploySiteToPages:
    @pytest.mark.asyncio
    async def test_returns_error_without_credentials(self):
        with patch.dict(
            "os.environ", {"CLOUDFLARE_API_TOKEN": "", "CLOUDFLARE_ACCOUNT_ID": ""}
        ):
            result = await deploy_site_to_pages("slug", "<html>test</html>")
        assert not result["success"]
        assert "credentials" in result["error"].lower()
