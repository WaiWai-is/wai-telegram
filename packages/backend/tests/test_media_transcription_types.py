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
