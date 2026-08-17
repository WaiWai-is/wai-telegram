import pytest
from pydantic import ValidationError


def _settings(**overrides):
    from app.core.config import Settings

    base = dict(
        environment="production",
        secret_key="a-real-secret",
        encryption_key="a-real-encryption-key",
        telegram_api_id=28306719,
        telegram_api_hash="a-real-hash",
        owner_user_id="2ab635cc-3f48-47ed-b07a-44dd9b0e6406",
        media_pipeline_enabled=True,
        telegram_bot_api_base_url="https://api.telegram.org",
    )
    base.update(overrides)
    return Settings(**base)


def test_cloud_bot_api_still_rejected_when_bot_downloads_are_used():
    with pytest.raises(ValidationError, match="local Bot API"):
        _settings(bot_media_downloads_enabled=True)


def test_archive_only_deployment_may_use_the_cloud_bot_api():
    """The archive pipeline downloads over MTProto, so it must not need the local server."""
    settings = _settings(bot_media_downloads_enabled=False)
    assert settings.media_pipeline_enabled is True


def test_local_bot_api_is_accepted_either_way():
    settings = _settings(
        bot_media_downloads_enabled=True,
        telegram_bot_api_base_url="http://127.0.0.1:8081",
    )
    assert settings.media_pipeline_enabled is True
