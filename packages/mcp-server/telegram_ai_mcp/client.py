import os
from datetime import date, datetime
from typing import Any
import logging

import httpx

logger = logging.getLogger(__name__)

MAX_LIMIT = 100
MAX_LOOKBACK_HOURS = 24 * 30
MAX_LOOKBACK_DAYS = 180


class TelegramAIClient:
    """Client for the Telegram AI backend API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        self.base_url = base_url or os.environ.get(
            "TELEGRAM_AI_URL", "http://localhost:8000"
        )
        self.api_key = api_key or os.environ.get("TELEGRAM_AI_KEY", "")
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=60.0,
            headers=headers,
        )

    async def close(self):
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:400] if e.response.text else "no response body"
            raise RuntimeError(
                f"Backend returned HTTP {e.response.status_code} for {method} {path}: {detail}"
            ) from e
        except httpx.RequestError as e:
            logger.error("Backend request error on %s %s: %s", method, path, e)
            raise RuntimeError(f"Backend request failed for {method} {path}: {e}") from e

    @staticmethod
    def _clamp(value: int, lower: int, upper: int) -> int:
        return max(lower, min(upper, value))

    async def search_messages(
        self,
        query: str,
        chat_ids: list[str] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Semantic search across Telegram messages."""
        limit = self._clamp(limit, 1, MAX_LIMIT)
        payload = {
            "query": query,
            "limit": limit,
        }
        if chat_ids:
            payload["chat_ids"] = chat_ids
        if date_from:
            payload["date_from"] = date_from.isoformat()
        if date_to:
            payload["date_to"] = date_to.isoformat()

        return await self._request("POST", "/api/v1/search", json=payload)

    async def list_chats(
        self,
        chat_type: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List synced Telegram chats."""
        params = {"limit": limit}
        if chat_type:
            params["chat_type"] = chat_type
        return await self._request("GET", "/api/v1/chats", params=params)

    async def get_chat(self, chat_id: str) -> dict[str, Any]:
        """Get details for a specific chat."""
        return await self._request("GET", f"/api/v1/chats/{chat_id}")

    async def get_messages(
        self,
        chat_id: str,
        limit: int = 50,
        before: str | None = None,
    ) -> dict[str, Any]:
        """Get messages from a specific chat with cursor pagination."""
        params: dict[str, Any] = {"limit": limit}
        if before:
            params["before"] = before
        return await self._request("GET", f"/api/v1/chats/{chat_id}/messages", params=params)

    async def sync_chat(
        self,
        chat_id: str,
        message_limit: int | None = None,
    ) -> dict[str, Any]:
        """Trigger message sync for a chat."""
        params: dict[str, Any] = {}
        if message_limit is not None:
            params["limit"] = message_limit
        return await self._request("POST", f"/api/v1/sync/chats/{chat_id}", params=params)

    async def get_sync_status(self, job_id: str) -> dict[str, Any]:
        """Get sync job status."""
        return await self._request("GET", f"/api/v1/sync/jobs/{job_id}")

    async def get_daily_digest(
        self,
        digest_date: date | None = None,
    ) -> dict[str, Any]:
        """Get or generate daily digest."""
        if digest_date:
            try:
                return await self._request(
                    "GET", f"/api/v1/digests/{digest_date.isoformat()}"
                )
            except RuntimeError as e:
                if "HTTP 404" in str(e):
                    # Generate if not found
                    pass
                else:
                    raise

        # Generate digest
        payload = {"date": digest_date.isoformat()} if digest_date else {}
        return await self._request("POST", "/api/v1/digests/generate", json=payload)

    async def get_chat_summary(
        self,
        chat_id: str,
        days: int = 7,
    ) -> dict[str, Any]:
        """Get summary of chat activity."""
        from datetime import timedelta, UTC

        days = self._clamp(days, 1, MAX_LOOKBACK_DAYS)
        date_from = datetime.now(UTC) - timedelta(days=days)

        # Get messages for the period
        result = await self.search_messages(
            query="*",
            chat_ids=[chat_id],
            date_from=date_from,
            limit=100,
        )

        chat = await self.get_chat(chat_id)

        return {
            "chat": chat,
            "period_days": days,
            "message_count": result.get("total", 0),
            "messages": result.get("results", [])[:20],
        }
