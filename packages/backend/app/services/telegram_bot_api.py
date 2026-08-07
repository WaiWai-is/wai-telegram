"""The only Telegram Bot API transport.

Full media mode points production to the local server. Explicit deferred mode
keeps Telegram's cloud endpoint until durable storage is attached.
"""

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class TelegramBotAPIError(RuntimeError):
    pass


def _redact(text: str) -> str:
    token = settings.telegram_bot_token
    return text.replace(token, "***") if token else text


class TelegramBotAPIClient:
    def __init__(self) -> None:
        if not settings.telegram_bot_token:
            raise TelegramBotAPIError("TELEGRAM_BOT_TOKEN is not configured")
        self.token = settings.telegram_bot_token
        self.base_url = settings.telegram_bot_api_base_url.rstrip("/")

    def _method_url(self, method: str) -> str:
        return f"{self.base_url}/bot{self.token}/{method}"

    def _file_url(self, file_path: str) -> str:
        return f"{self.base_url}/file/bot{self.token}/{file_path.lstrip('/')}"

    async def call(
        self,
        method: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = 30.0,
    ) -> Any:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    self._method_url(method),
                    json=json,
                    params=params,
                )
        except httpx.HTTPError as exc:
            raise TelegramBotAPIError(
                f"Telegram Bot API request failed ({type(exc).__name__})"
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise TelegramBotAPIError("Telegram Bot API returned invalid JSON") from exc
        if response.status_code >= 400 or not payload.get("ok"):
            detail = _redact(str(payload.get("description") or response.text))[:300]
            raise TelegramBotAPIError(
                f"Telegram Bot API {method} failed with status "
                f"{response.status_code}: {detail}"
            )
        return payload.get("result")

    async def get_file(self, file_id: str) -> dict[str, Any]:
        result = await self.call(
            "getFile",
            params={"file_id": file_id},
            timeout=None,
        )
        if not isinstance(result, dict) or not result.get("file_path"):
            raise TelegramBotAPIError("Telegram getFile returned no file_path")
        return result

    async def download_file_to(self, file_id: str, destination: Path) -> Path:
        info = await self.get_file(file_id)
        file_path = str(info["file_path"])
        local_source = Path(file_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if local_source.is_absolute():
            if not local_source.is_file():
                raise TelegramBotAPIError("Telegram Bot API file_path does not exist")
            await asyncio.to_thread(shutil.copyfile, local_source, destination)
        else:
            try:
                timeout = httpx.Timeout(
                    None,
                    connect=15.0,
                    read=settings.media_download_stall_timeout_seconds,
                    write=30.0,
                    pool=30.0,
                )
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "GET", self._file_url(file_path)
                    ) as response:
                        response.raise_for_status()
                        with destination.open("wb") as output:
                            async for chunk in response.aiter_bytes(
                                settings.media_download_chunk_bytes
                            ):
                                output.write(chunk)
            except httpx.HTTPError as exc:
                raise TelegramBotAPIError(
                    f"Telegram file download failed ({type(exc).__name__})"
                ) from exc
        if not destination.is_file() or destination.stat().st_size == 0:
            raise TelegramBotAPIError("Telegram file download returned no bytes")
        return destination


def get_bot_api_client() -> TelegramBotAPIClient:
    return TelegramBotAPIClient()
