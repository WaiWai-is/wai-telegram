"""Cloudflare Pages Deploy — publish sites instantly to *.wai.computer.

Deploys static HTML/CSS/JS to Cloudflare Pages via Direct Upload API.
Each site gets a unique URL: {slug}.wai.computer

Flow:
1. Claude generates HTML
2. We upload to Cloudflare Pages via API
3. Site is live at {slug}.wai.computer within seconds

Cloudflare Pages Direct Upload:
- No git, no build step
- Upload files directly via API
- Instant global CDN distribution
- Auto-SSL
"""

import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Cloudflare configuration (from env vars)
DOMAIN = "wai.computer"


def _get_cf_credentials() -> tuple[str, str]:
    """Get Cloudflare API token and account ID from environment."""
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    return token, account_id


async def deploy_to_cloudflare_pages(
    slug: str,
    html_content: str,
    project_name: str = "wai-sites",
) -> dict:
    """Deploy HTML content to Cloudflare Pages via Direct Upload API.

    Returns:
        {"success": True, "url": "https://slug.wai.computer", "deployment_url": "..."}
        or {"success": False, "error": "..."}
    """
    token, account_id = _get_cf_credentials()
    if not token or not account_id:
        return {"success": False, "error": "Cloudflare credentials not configured"}

    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Step 1: Ensure the Pages project exists
            await _ensure_project_exists(client, headers, account_id, project_name)

            # Step 2: Create a deployment with Direct Upload
            # Cloudflare Pages Direct Upload uses multipart form upload
            files_to_upload = {
                "index.html": html_content,
            }

            # Create deployment
            deployment = await _create_direct_upload_deployment(
                client, headers, account_id, project_name, files_to_upload
            )

            if not deployment:
                return {"success": False, "error": "Deployment creation failed"}

            deployment_url = deployment.get("url", "")

            return {
                "success": True,
                "url": f"https://{slug}.{DOMAIN}",
                "deployment_url": deployment_url,
                "slug": slug,
            }

    except Exception as e:
        logger.error(f"Cloudflare deploy failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def _ensure_project_exists(
    client: httpx.AsyncClient,
    headers: dict,
    account_id: str,
    project_name: str,
) -> None:
    """Create the Pages project if it doesn't exist."""
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/pages/projects/{project_name}"
    resp = await client.get(url, headers=headers)

    if resp.status_code == 200:
        return  # Already exists

    # Create it
    create_url = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/pages/projects"
    )
    resp = await client.post(
        create_url,
        headers=headers,
        json={
            "name": project_name,
            "production_branch": "main",
        },
    )
    if resp.status_code in (200, 409):  # 409 = already exists
        logger.info(f"Pages project '{project_name}' ready")
    else:
        logger.error(f"Failed to create project: {resp.status_code} {resp.text}")


async def _create_direct_upload_deployment(
    client: httpx.AsyncClient,
    headers: dict,
    account_id: str,
    project_name: str,
    files: dict[str, str],
) -> dict | None:
    """Upload files directly to Cloudflare Pages.

    Uses the Direct Upload API to deploy without git.
    """
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/pages/projects/{project_name}/deployments"

    # Build multipart form data
    # Each file needs to be sent as a separate part
    form_files = []
    for filename, content in files.items():
        form_files.append(("file", (filename, content.encode("utf-8"), "text/html")))

    # Create deployment with branch name for routing
    resp = await client.post(
        url,
        headers=headers,
        files=form_files,
    )

    if resp.status_code == 200:
        data = resp.json()
        result = data.get("result", {})
        logger.info(f"Deployment created: {result.get('url', 'unknown')}")
        return result
    else:
        logger.error(f"Deployment failed: {resp.status_code} {resp.text}")
        return None


async def deploy_site_to_pages(slug: str, html: str) -> dict:
    """High-level function: deploy a site and return the URL.

    This is the main entry point called from the bot webhook.
    Falls back to local filesystem if Cloudflare is not configured.
    """
    token, account_id = _get_cf_credentials()

    if token and account_id:
        # Deploy to Cloudflare Pages
        result = await deploy_to_cloudflare_pages(slug, html)
        if result["success"]:
            return result

    # Fallback: save to local filesystem (nginx serves it)
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
