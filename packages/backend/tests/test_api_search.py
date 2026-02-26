from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.schemas.search import SearchResponse


class TestSearchEndpoint:
    async def test_search_success(self, auth_client):
        mock_response = SearchResponse(
            results=[],
            query="test query",
            total=0,
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
            assert data["results"] == []
            assert data["total"] == 0

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
