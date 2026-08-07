import pytest
from app.schemas.auth import ApiKeyCreateRequest
from pydantic import ValidationError


class TestApiKeyCreateRequest:
    def test_valid_name(self):
        req = ApiKeyCreateRequest(name="My API Key")
        assert req.name == "My API Key"

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            ApiKeyCreateRequest(name="")

    def test_name_max_length(self):
        req = ApiKeyCreateRequest(name="a" * 100)
        assert len(req.name) == 100

    def test_name_too_long_rejected(self):
        with pytest.raises(ValidationError):
            ApiKeyCreateRequest(name="a" * 101)
