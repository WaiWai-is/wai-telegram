import pytest


def _resolve(monkeypatch, value):
    from app.services import media_content_service

    monkeypatch.setattr(
        media_content_service.settings,
        "media_transcription_types",
        value,
        raising=False,
    )
    return media_content_service._configured_transcription_types()


def test_unset_keeps_every_transcribable_type(monkeypatch):
    assert _resolve(monkeypatch, None) == {"voice", "video_note", "audio", "video"}


def test_empty_string_is_treated_as_unset(monkeypatch):
    assert _resolve(monkeypatch, "") == {"voice", "video_note", "audio", "video"}


def test_narrowing_drops_video_and_audio(monkeypatch):
    assert _resolve(monkeypatch, "voice,video_note") == {"voice", "video_note"}


def test_whitespace_and_blank_entries_are_ignored(monkeypatch):
    assert _resolve(monkeypatch, " voice , , video_note ") == {"voice", "video_note"}


def test_unknown_type_is_rejected_rather_than_silently_dropped(monkeypatch):
    with pytest.raises(ValueError, match="sticker"):
        _resolve(monkeypatch, "voice,sticker")


def _accumulates(monkeypatch, types):
    from app.services import media_content_service

    monkeypatch.setattr(
        media_content_service, "MEDIA_TRANSCRIPTION_TYPES", frozenset(types)
    )
    return media_content_service.scope_accumulates_media()


def test_speech_only_scope_does_not_accumulate_media(monkeypatch):
    assert _accumulates(monkeypatch, {"voice", "video_note"}) is False


def test_video_in_scope_accumulates_media(monkeypatch):
    assert _accumulates(monkeypatch, {"voice", "video_note", "video"}) is True


def test_audio_in_scope_accumulates_media(monkeypatch):
    assert _accumulates(monkeypatch, {"voice", "audio"}) is True


def test_media_root_needs_no_mount_when_nothing_accumulates(monkeypatch, tmp_path):
    """A speech-only deployment stages a file for seconds, so a volume is not required."""
    from app.services import media_cache_service, media_content_service

    monkeypatch.setattr(
        media_content_service, "MEDIA_TRANSCRIPTION_TYPES", frozenset({"voice"})
    )
    monkeypatch.setattr(media_cache_service.settings, "environment", "production")
    monkeypatch.setattr(media_cache_service.settings, "media_root", tmp_path)

    assert media_cache_service._ensure_media_root() == tmp_path


def test_media_root_still_needs_a_mount_when_video_is_in_scope(monkeypatch, tmp_path):
    from app.services import media_cache_service, media_content_service

    monkeypatch.setattr(
        media_content_service,
        "MEDIA_TRANSCRIPTION_TYPES",
        frozenset({"voice", "video"}),
    )
    monkeypatch.setattr(media_cache_service.settings, "environment", "production")
    monkeypatch.setattr(media_cache_service.settings, "media_root", tmp_path)

    with pytest.raises(media_cache_service.MediaCacheError, match="not mounted"):
        media_cache_service._ensure_media_root()
