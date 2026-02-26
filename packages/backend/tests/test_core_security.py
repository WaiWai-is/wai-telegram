from datetime import timedelta

import pytest
from app.core.security import (
    compute_api_key_prefix,
    create_access_token,
    create_refresh_token,
    decode_token,
    decrypt_session,
    encrypt_session,
    generate_api_key,
    get_key_hint,
    hash_api_key,
    hash_password,
    verify_api_key,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        password = "SecureP@ssw0rd"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("CorrectPassword1")
        assert verify_password("WrongPassword1", hashed) is False

    def test_different_hashes_for_same_password(self):
        password = "SamePassword1"
        h1 = hash_password(password)
        h2 = hash_password(password)
        assert h1 != h2  # bcrypt uses random salt


class TestApiKeys:
    def test_generate_api_key_starts_with_prefix(self):
        key = generate_api_key()
        assert key.startswith("wai_")
        assert len(key) > 10

    def test_hash_and_verify_api_key(self):
        key = generate_api_key()
        hashed = hash_api_key(key)
        assert verify_api_key(key, hashed) is True

    def test_verify_wrong_api_key(self):
        key = generate_api_key()
        hashed = hash_api_key(key)
        assert verify_api_key("wai_wrong_key", hashed) is False

    def test_compute_api_key_prefix_deterministic(self):
        key = "wai_test_key_123"
        p1 = compute_api_key_prefix(key)
        p2 = compute_api_key_prefix(key)
        assert p1 == p2
        assert len(p1) == 16

    def test_get_key_hint(self):
        key = "wai_abcdefghijklmnop"
        hint = get_key_hint(key)
        assert hint == "wai_****mnop"


class TestJWT:
    def test_create_and_decode_access_token(self):
        data = {"sub": "user-123"}
        token = create_access_token(data)
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"
        assert payload["type"] == "access"

    def test_create_and_decode_refresh_token(self):
        data = {"sub": "user-456"}
        token = create_refresh_token(data)
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user-456"
        assert payload["type"] == "refresh"

    def test_expired_token_returns_none(self):
        data = {"sub": "user-789"}
        token = create_access_token(data, expires_delta=timedelta(seconds=-1))
        payload = decode_token(token)
        assert payload is None

    def test_invalid_token_returns_none(self):
        payload = decode_token("not.a.valid.token")
        assert payload is None

    def test_access_token_has_type_access(self):
        token = create_access_token({"sub": "user-1"})
        payload = decode_token(token)
        assert payload["type"] == "access"

    def test_refresh_token_has_type_refresh(self):
        token = create_refresh_token({"sub": "user-1"})
        payload = decode_token(token)
        assert payload["type"] == "refresh"

    def test_custom_expiry(self):
        token = create_access_token(
            {"sub": "user-1"},
            expires_delta=timedelta(hours=1),
        )
        payload = decode_token(token)
        assert payload is not None


class TestFernetEncryption:
    def test_encrypt_and_decrypt_session(self):
        original = "session_string_data_here"
        encrypted = encrypt_session(original)
        assert encrypted != original
        decrypted = decrypt_session(encrypted)
        assert decrypted == original

    def test_decrypt_wrong_data_raises(self):
        with pytest.raises(Exception):
            decrypt_session("not-valid-fernet-data")
