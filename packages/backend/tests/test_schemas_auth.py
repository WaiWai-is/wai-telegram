import pytest
from app.schemas.auth import ApiKeyCreateRequest, RegisterRequest
from pydantic import ValidationError


class TestRegisterRequest:
    def test_valid_registration(self):
        req = RegisterRequest(email="user@example.com", password="StrongPass1")
        assert req.email == "user@example.com"

    def test_password_too_short(self):
        with pytest.raises(ValidationError, match="at least 8 characters"):
            RegisterRequest(email="user@example.com", password="Short1")

    def test_password_no_uppercase(self):
        with pytest.raises(ValidationError, match="uppercase"):
            RegisterRequest(email="user@example.com", password="alllowercase1")

    def test_password_no_digit(self):
        with pytest.raises(ValidationError, match="digit"):
            RegisterRequest(email="user@example.com", password="NoDigitHere")

    def test_valid_strong_password(self):
        req = RegisterRequest(email="user@example.com", password="MyStr0ng!")
        assert req.password == "MyStr0ng!"

    def test_invalid_email(self):
        with pytest.raises(ValidationError):
            RegisterRequest(email="not-an-email", password="StrongPass1")


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
