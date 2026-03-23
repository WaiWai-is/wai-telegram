from unittest.mock import AsyncMock, patch

from app.schemas.search import SearchResponse, SearchResultItem
from app.services.search_service import SearchServiceError


class TestSearchEndpoint:
    async def test_search_success(self, auth_client):
        mock_response = SearchResponse(
            results=[
                SearchResultItem(
                    id="00000000-0000-0000-0000-000000000001",
                    chat_id="00000000-0000-0000-0000-000000000002",
                    chat_title="Test Chat",
                    chat_type="supergroup",
                    chat_telegram_id=-1001234567890,
                    chat_username="test_chat",
                    telegram_message_id=42,
                    text="hello",
                    sender_name="John",
                    is_outgoing=False,
                    sent_at="2026-03-10T12:00:00Z",
                    similarity=0.91,
                    has_media=False,
                )
            ],
            query="test query",
            total=1,
        )
        with patch(
            "app.api.v1.search.semantic_search",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            response = await auth_client.post(
                "/api/v1/search",
                json={"query": "test query"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["query"] == "test query"
            assert data["results"][0]["chat_type"] == "supergroup"
            assert data["results"][0]["chat_telegram_id"] == -1001234567890
            assert data["results"][0]["chat_username"] == "test_chat"
            assert data["total"] == 1

    async def test_search_unauthenticated(self, client):
        response = await client.post(
            "/api/v1/search",
            json={"query": "hello"},
        )
        assert response.status_code == 401

    async def test_search_empty_query(self, auth_client):
        # Empty string query should still be valid (no min_length constraint)
        mock_response = SearchResponse(results=[], query="", total=0)
        with patch(
            "app.api.v1.search.semantic_search",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            response = await auth_client.post(
                "/api/v1/search",
                json={"query": ""},
            )
            assert response.status_code == 200

    async def test_search_service_unavailable_returns_503(self, auth_client):
        with patch(
            "app.api.v1.search.semantic_search",
            new_callable=AsyncMock,
            side_effect=SearchServiceError("Search is temporarily unavailable"),
        ):
            response = await auth_client.post(
                "/api/v1/search",
                json={"query": "test query"},
            )

        assert response.status_code == 503
        assert response.json()["detail"] == "Search is temporarily unavailable"

    async def test_search_service_unavailable_logs_warning(self, auth_client):
        with patch(
            "app.api.v1.search.semantic_search",
            new_callable=AsyncMock,
            side_effect=SearchServiceError("Search is temporarily unavailable"),
        ), patch("app.api.v1.search.logger.warning") as mock_logger_warning:
            response = await auth_client.post(
                "/api/v1/search",
                json={"query": "test query"},
            )

        assert response.status_code == 503
        mock_logger_warning.assert_called_once()
        assert mock_logger_warning.call_args.args[0] == (
            "Search request failed with service unavailability"
        )
