from uuid import uuid4

import pytest
from app.models.chat import ChatType
from app.schemas.search import SearchMode, SearchRequest
from pydantic import ValidationError


class TestSearchRequest:
    def test_valid_search(self):
        req = SearchRequest(query="hello")
        assert req.query == "hello"
        assert req.limit == 20  # default

    def test_zero_limit_rejected(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="hello", limit=0)

    def test_negative_limit_rejected(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="hello", limit=-1)

    def test_limit_above_max_rejected(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="hello", limit=101)

    def test_limit_at_max(self):
        req = SearchRequest(query="hello", limit=100)
        assert req.limit == 100

    def test_limit_at_min(self):
        req = SearchRequest(query="hello", limit=1)
        assert req.limit == 1

    def test_chat_ids_filter(self):
        chat_id = uuid4()
        req = SearchRequest(query="hello", chat_ids=[chat_id])
        assert req.chat_ids == [chat_id]

    def test_date_filters(self):
        from datetime import UTC, datetime

        req = SearchRequest(
            query="hello",
            date_from=datetime(2024, 1, 1, tzinfo=UTC),
            date_to=datetime(2024, 12, 31, tzinfo=UTC),
        )
        assert req.date_from is not None
        assert req.date_to is not None

    def test_defaults(self):
        req = SearchRequest(query="test")
        assert req.chat_ids is None
        assert req.chat_types is None
        assert req.date_from is None
        assert req.date_to is None
        assert req.limit == 20
        assert req.mode == SearchMode.HYBRID

    def test_exact_mode_and_chat_type_filters(self):
        req = SearchRequest(
            query="Альфа-Банк",
            mode="exact",
            chat_types=["group", "supergroup"],
        )

        assert req.mode == SearchMode.EXACT
        assert req.chat_types == [ChatType.GROUP, ChatType.SUPERGROUP]

    def test_invalid_mode_is_rejected(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="hello", mode="fuzzy")
