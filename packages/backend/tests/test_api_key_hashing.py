"""API keys are hashed for speed; passwords keep the memory-hard KDF."""


def test_new_keys_use_sha256():
    from app.core.security import hash_api_key

    assert hash_api_key("wai_live_abc123").startswith("sha256$")


def test_a_key_verifies_against_its_own_hash():
    from app.core.security import hash_api_key, verify_api_key

    key = "wai_live_abc123"
    assert verify_api_key(key, hash_api_key(key)) is True


def test_a_different_key_is_rejected():
    from app.core.security import hash_api_key, verify_api_key

    assert verify_api_key("wrong", hash_api_key("wai_live_abc123")) is False


def test_keys_issued_before_the_change_still_work():
    """Existing keys carry an Argon2 hash and must keep authenticating."""
    from app.core.security import password_hash, verify_api_key

    key = "legacy_key_value"
    legacy_hash = password_hash.hash(key)
    assert legacy_hash.startswith("$argon2") or legacy_hash.startswith("$2")
    assert verify_api_key(key, legacy_hash) is True
    assert verify_api_key("wrong", legacy_hash) is False


def test_passwords_still_use_the_slow_hash():
    from app.core.security import hash_password

    assert hash_password("hunter2").startswith("$")
