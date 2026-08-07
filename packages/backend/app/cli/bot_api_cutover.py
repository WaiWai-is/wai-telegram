"""One-time, explicit migration from Telegram cloud Bot API to localhost."""

import argparse
import asyncio
import hashlib

import httpx

from app.core.config import get_settings
from app.services.telegram_bot_api import TelegramBotAPIClient, TelegramBotAPIError


async def _cloud_call(token: str, method: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/{method}"
            )
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(f"Cloud Bot API {method} request failed") from exc
    if response.status_code >= 400 or not payload.get("ok"):
        description = str(payload.get("description") or "request rejected")[:200]
        raise RuntimeError(f"Cloud Bot API {method} rejected: {description}")


async def configure_local_bot_api(
    public_base_url: str, *, allow_cloud_logout: bool
) -> dict:
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    local = TelegramBotAPIClient()
    already_local = False
    try:
        await local.call("getMe")
        already_local = True
    except TelegramBotAPIError as exc:
        if not allow_cloud_logout:
            raise RuntimeError(
                "Local Bot API verification failed; cloud fallback is disabled"
            ) from exc

    if not already_local:
        await _cloud_call(token, "deleteWebhook")
        await _cloud_call(token, "logOut")
        await local.call("getMe", timeout=60.0)

    secret = hashlib.sha256(token.encode()).hexdigest()[:32]
    webhook_url = f"{public_base_url.rstrip('/')}/api/v1/bot/webhook/{secret}"
    await local.call(
        "setWebhook",
        json={
            "url": webhook_url,
            "drop_pending_updates": False,
            "max_connections": 100,
        },
        timeout=60.0,
    )
    info = await local.call("getWebhookInfo")
    if not isinstance(info, dict) or info.get("url") != webhook_url:
        raise RuntimeError("Local Bot API webhook verification failed")
    return {
        "already_local": already_local,
        "webhook_configured": True,
        "pending_update_count": int(info.get("pending_update_count", 0) or 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--public-base-url",
        default="https://telegram.waiwai.is",
    )
    parser.add_argument(
        "--initial-cloud-cutover",
        action="store_true",
        help="One-time authorization to log the bot out of the cloud Bot API.",
    )
    parser.add_argument(
        "--verify-local",
        action="store_true",
        help="Verify/configure localhost only; never calls the cloud Bot API.",
    )
    args = parser.parse_args()
    if args.initial_cloud_cutover == args.verify_local:
        parser.error("choose exactly one of --initial-cloud-cutover or --verify-local")
    print(
        asyncio.run(
            configure_local_bot_api(
                args.public_base_url,
                allow_cloud_logout=args.initial_cloud_cutover,
            )
        )
    )


if __name__ == "__main__":
    main()
