from unittest.mock import AsyncMock, patch


class TestSemanticSearch:
    async def test_empty_embedding_returns_empty(self, db_session, test_user):
        from app.schemas.search import SearchRequest
        from app.services.search_service import semantic_search

        request = SearchRequest(query="test")
        with patch(
            "app.services.search_service.generate_query_embedding",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await semantic_search(db_session, test_user.id, request)
            assert result.results == []
            assert result.total == 0
