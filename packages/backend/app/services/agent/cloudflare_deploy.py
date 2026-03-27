"""Cloudflare Pages Deploy — publish sites instantly to *.wai.computer.

Uses Wrangler-style Direct Upload: write HTML to temp dir, call Wrangler API.
Each site deploys to the shared `wai-sites` Pages project.
Custom domains like {slug}.wai.computer route via wildcard CNAME.

Verified working: test deploy at https://c3d1bb69.wai-sites.pages.dev
"""

import hashlib
import logging
import os
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

DOMAIN = "wai.computer"
PROJECT_NAME = "wai-sites"


def _get_cf_credentials() -> tuple[str, str]:
    """Get Cloudflare API token and account ID from environment."""
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    return token, account_id


async def deploy_to_cloudflare_pages(slug: str, html_content: str) -> dict:
    """Deploy HTML to Cloudflare Pages via Direct Upload API.

    Uses the same approach as Wrangler CLI: hash-based manifest + file upload.
    """
    token, account_id = _get_cf_credentials()
    if not token or not account_id:
        return {"success": False, "error": "Cloudflare credentials not configured"}

    try:
        # Write HTML to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8"
        ) as f:
            f.write(html_content)
            temp_path = f.name

        # Calculate MD5 hash for manifest
        content_hash = hashlib.md5(html_content.encode("utf-8")).hexdigest()

        headers = {"Authorization": f"Bearer {token}"}
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/pages/projects/{PROJECT_NAME}/deployments"

        # Manifest maps: path → content hash
        manifest = (
            f'{{"/{slug}/index.html":"{content_hash}","/index.html":"{content_hash}"}}'
        )

        async with httpx.AsyncClient(timeout=30) as client:
            with open(temp_path, "rb") as file_obj:
                resp = await client.post(
                    url,
                    headers=headers,
                    data={"manifest": manifest},
                    files={content_hash: ("index.html", file_obj, "text/html")},
                )

        # Clean up
        os.unlink(temp_path)

        if resp.status_code == 200:
            data = resp.json()
            result = data.get("result", {})
            deploy_url = result.get("url", "")
            logger.info(f"Cloudflare deploy OK: {deploy_url} for slug={slug}")
            return {
                "success": True,
                "url": f"https://{slug}.{DOMAIN}",
                "deployment_url": deploy_url,
                "pages_url": f"https://{PROJECT_NAME}.pages.dev/{slug}/",
                "slug": slug,
                "method": "cloudflare",
            }
        else:
            error = resp.text[:200]
            logger.error(f"Cloudflare deploy failed: {resp.status_code} {error}")
            return {"success": False, "error": f"API error {resp.status_code}: {error}"}

    except Exception as e:
        logger.error(f"Cloudflare deploy error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def deploy_site_to_pages(slug: str, html: str) -> dict:
    """High-level deploy: Cloudflare Pages → local fallback.

    This is the main entry point called from site_builder.py.
    """
    token, account_id = _get_cf_credentials()

    if token and account_id:
        result = await deploy_to_cloudflare_pages(slug, html)
        if result["success"]:
            return result
        logger.warning(f"Cloudflare deploy failed, trying local: {result.get('error')}")

    # Fallback: local filesystem
    try:
        sites_dir = Path("/var/www/sites")
        site_dir = sites_dir / slug
        site_dir.mkdir(parents=True, exist_ok=True)
        (site_dir / "index.html").write_text(html, encoding="utf-8")
        return {
            "success": True,
            "url": f"https://{slug}.{DOMAIN}",
            "slug": slug,
            "method": "local",
        }
    except Exception as e:
        return {"success": False, "error": f"Local deploy failed: {e}"}
