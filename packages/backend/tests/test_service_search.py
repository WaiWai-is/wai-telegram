import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4


class TestSemanticSearch:
    async def test_blank_query_returns_empty_without_embeddings(self, db_session, test_user):
        from app.schemas.search import SearchRequest
        from app.services.search_service import semantic_search

        request = SearchRequest(query="   ")
        with patch(
            "app.services.search_service.generate_query_embedding",
            new_callable=AsyncMock,
        ) as mock_embedding, patch(
            "app.services.search_service.logger.info"
        ) as mock_logger_info:
            result = await semantic_search(db_session, test_user.id, request)

        assert result.results == []
        assert result.total == 0
        mock_embedding.assert_not_awaited()
        mock_logger_info.assert_called_once()
        assert mock_logger_info.call_args.args[0] == "Search skipped for blank query"

    async def test_empty_embedding_returns_empty(self, db_session, test_user):
        from app.schemas.search import SearchRequest
        from app.services.search_service import semantic_search

        request = SearchRequest(query="test")
        with patch(
            "app.services.search_service.generate_query_embedding",
            new_callable=AsyncMock,
            return_value=[],
        ), patch("app.services.search_service.logger.info") as mock_logger_info:
            result = await semantic_search(db_session, test_user.id, request)
            assert result.results == []
            assert result.total == 0
        mock_logger_info.assert_called_once()
        assert mock_logger_info.call_args.args[0] == "Search returned empty embedding result"

    async def test_includes_chat_username_when_available(self, test_user):
        from app.schemas.search import SearchRequest
        from app.services.search_service import semantic_search

        request = SearchRequest(query="test")
        row = SimpleNamespace(
            id=uuid4(),
            chat_id=uuid4(),
            chat_title="Test Chat",
            chat_type="SUPERGROUP",
            chat_telegram_id=-1001234567890,
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
        assert result.results[0].chat_type == "supergroup"
        assert result.results[0].chat_telegram_id == -1001234567890
        assert result.results[0].chat_username == "test_chat"

    async def test_keyword_search_sql_omits_explicit_escape_clause(self, test_user):
        from app.schemas.search import SearchRequest
        from app.services.search_service import _keyword_search

        row = SimpleNamespace(
            id=uuid4(),
            chat_id=uuid4(),
            chat_title="Test Chat",
            chat_type="PRIVATE",
            chat_telegram_id=123,
            chat_username=None,
            telegram_message_id=7,
            text="wai message",
            sender_name="John",
            is_outgoing=False,
            sent_at="2026-03-10T12:00:00Z",
            similarity=1.0,
            has_media=False,
            media_type=None,
            transcribed_at=None,
        )
        mock_result = SimpleNamespace(fetchall=lambda: [row])
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _keyword_search(mock_db, test_user.id, SearchRequest(query="wai"))

        sql_text = str(mock_db.execute.call_args.args[0])
        assert "ESCAPE" not in sql_text
        assert result.results[0].chat_type == "private"

    async def test_falls_back_to_keyword_search_when_embeddings_fail(self, test_user):
        from app.schemas.search import SearchRequest
        from app.services.search_service import semantic_search

        request = SearchRequest(query="test")
        expected = SimpleNamespace(results=[], query="test", total=0)
        mock_db = AsyncMock()

        with patch(
            "app.services.search_service.generate_query_embedding",
            new_callable=AsyncMock,
            side_effect=RuntimeError("openai failed"),
        ), patch(
            "app.services.search_service._keyword_search",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_keyword_search, patch(
            "app.services.search_service.logger.exception"
        ) as mock_logger_exception, patch(
            "app.services.search_service.logger.info"
        ) as mock_logger_info:
            result = await semantic_search(mock_db, test_user.id, request)

        assert result is expected
        mock_keyword_search.assert_awaited_once_with(mock_db, test_user.id, request)
        assert mock_logger_exception.call_args.args[0] == (
            "Semantic search embedding generation failed; falling back to keyword search"
        )
        assert mock_logger_info.call_args.args[0] == (
            "Keyword search fallback succeeded after embedding failure"
        )

    async def test_falls_back_to_keyword_search_when_vector_query_fails(self, test_user):
        from app.schemas.search import SearchRequest
        from app.services.search_service import semantic_search

        request = SearchRequest(query="test")
        expected = SimpleNamespace(results=[], query="test", total=0)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=RuntimeError("vector failed"))

        with patch(
            "app.services.search_service.generate_query_embedding",
            new_callable=AsyncMock,
            return_value=[0.1, 0.2, 0.3],
        ), patch(
            "app.services.search_service._keyword_search",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_keyword_search, patch(
            "app.services.search_service.logger.exception"
        ) as mock_logger_exception, patch(
            "app.services.search_service.logger.info"
        ) as mock_logger_info:
            result = await semantic_search(mock_db, test_user.id, request)

        assert result is expected
        mock_keyword_search.assert_awaited_once_with(mock_db, test_user.id, request)
        assert mock_logger_exception.call_args.args[0] == (
            "Semantic vector search failed; falling back to keyword search"
        )
        assert mock_logger_info.call_args.args[0] == (
            "Keyword search fallback succeeded after vector search failure"
        )

    async def test_raises_when_all_search_strategies_fail(self, test_user):
        from app.schemas.search import SearchRequest
        from app.services.search_service import SearchServiceError, semantic_search

        request = SearchRequest(query="test")
        mock_db = AsyncMock()

        with patch(
            "app.services.search_service.generate_query_embedding",
            new_callable=AsyncMock,
            side_effect=RuntimeError("openai failed"),
        ), patch(
            "app.services.search_service._keyword_search",
            new_callable=AsyncMock,
            side_effect=RuntimeError("keyword failed"),
        ):
            with pytest.raises(SearchServiceError, match="temporarily unavailable"):
                await semantic_search(mock_db, test_user.id, request)
