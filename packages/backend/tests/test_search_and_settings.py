import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.search import SearchRequest


def test_search_request_rejects_zero_limit() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="hello", limit=0)


def test_search_request_accepts_valid_limit() -> None:
    req = SearchRequest(query="hello", limit=1)
    assert req.limit == 1


def test_settings_require_secrets_outside_dev() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="staging")
