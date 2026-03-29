"""Cloudflare Pages Deploy — publish sites instantly to *.wai.computer.

Uses `wrangler pages deploy` CLI for reliable deployments.
Each site deploys to the shared `wai-sites` Pages project.
Custom domains like {slug}.wai.computer route via wildcard CNAME.
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

DOMAIN = "wai.computer"
PROJECT_NAME = "wai-sites"


async def deploy_to_cloudflare_pages(slug: str, html_content: str) -> dict:
    """Deploy HTML to Cloudflare Pages via wrangler CLI."""
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    if not token or not account_id:
        return {"success": False, "error": "Cloudflare credentials not configured"}

    try:
        # Write HTML to a temp directory (wrangler deploys a directory)
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "index.html"
            index_path.write_text(html_content, encoding="utf-8")

            proc = await asyncio.create_subprocess_exec(
                "wrangler", "pages", "deploy", tmpdir,
                f"--project-name={PROJECT_NAME}",
                "--commit-dirty=true",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={
                    **os.environ,
                    "CLOUDFLARE_API_TOKEN": token,
                    "CLOUDFLARE_ACCOUNT_ID": account_id,
                },
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

        stdout_text = stdout.decode()
        stderr_text = stderr.decode()

        if proc.returncode == 0:
            # Extract deployment URL from wrangler output
            deploy_url = ""
            for line in stdout_text.splitlines():
                if "https://" in line and ".pages.dev" in line:
                    deploy_url = line.strip().split()[-1]
                    break

            logger.info(f"Cloudflare deploy OK: {deploy_url} for slug={slug}")
            return {
                "success": True,
                "url": deploy_url or f"https://{PROJECT_NAME}.pages.dev",
                "slug": slug,
                "method": "cloudflare",
            }
        else:
            error = (stderr_text or stdout_text)[:300]
            logger.error(f"Wrangler deploy failed (exit {proc.returncode}): {error}")
            return {"success": False, "error": f"Wrangler error: {error}"}

    except asyncio.TimeoutError:
        logger.error("Wrangler deploy timed out after 60s")
        return {"success": False, "error": "Deploy timed out"}
    except Exception as e:
        logger.error(f"Cloudflare deploy error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def deploy_site_to_pages(slug: str, html: str) -> dict:
    """High-level deploy entry point called from site_builder.py."""
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")

    if token and account_id:
        return await deploy_to_cloudflare_pages(slug, html)

    return {"success": False, "error": "Cloudflare credentials not configured"}
