from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4


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

    async def test_includes_chat_username_when_available(self, test_user):
        from app.schemas.search import SearchRequest
        from app.services.search_service import semantic_search

        request = SearchRequest(query="test")
        row = SimpleNamespace(
            id=uuid4(),
            chat_id=uuid4(),
            chat_title="Test Chat",
            chat_username="test_chat",
            telegram_message_id=42,
            text="hello",
            sender_name="John",
            is_outgoing=False,
            sent_at="2026-03-10T12:00:00Z",
            similarity=0.91,
            has_media=False,
            media_type=None,
            transcribed_at=None,
        )
        mock_result = SimpleNamespace(fetchall=lambda: [row])
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.services.search_service.generate_query_embedding",
            new_callable=AsyncMock,
            return_value=[0.1, 0.2, 0.3],
        ):
            result = await semantic_search(mock_db, test_user.id, request)

        assert result.total == 1
        assert result.results[0].chat_username == "test_chat"
