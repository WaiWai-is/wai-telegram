"""Screenshot Service — capture website previews via Microlink API.

Uses Microlink's free screenshot API to generate preview images of deployed sites.
No dependencies beyond httpx (already in the project).
"""

import logging

import httpx

logger = logging.getLogger(__name__)

MICROLINK_URL = "https://api.microlink.io/"
SCREENSHOT_TIMEOUT = 15


async def get_screenshot_url(site_url: str) -> str | None:
    """Get a screenshot URL for a website via Microlink API.

    Returns the direct image URL on success, None on any error.
    """
    try:
        async with httpx.AsyncClient(timeout=SCREENSHOT_TIMEOUT) as client:
            resp = await client.get(
                MICROLINK_URL,
                params={
                    "url": site_url,
                    "screenshot": "true",
                    "viewport.width": "1280",
                    "viewport.height": "720",
                },
            )
            if resp.status_code != 200:
                logger.warning(f"Microlink returned {resp.status_code} for {site_url}")
                return None

            data = resp.json()
            screenshot_url = data.get("data", {}).get("screenshot", {}).get("url")
            if not screenshot_url:
                logger.warning(
                    f"No screenshot URL in Microlink response for {site_url}"
                )
                return None

            return screenshot_url

    except httpx.TimeoutException:
        logger.warning(f"Microlink timeout for {site_url}")
        return None
    except Exception as e:
        logger.warning(f"Screenshot failed for {site_url}: {e}")
        return None
