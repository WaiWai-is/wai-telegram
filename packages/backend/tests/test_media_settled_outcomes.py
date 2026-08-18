"""Media that can never yield text is settled, not failed."""

import pytest


def _errors():
    from app.services.media_processing_service import (
        MediaDownloadError,
        MediaNoSpeechError,
        MediaSourceDeleted,
    )

    return MediaSourceDeleted, MediaNoSpeechError, MediaDownloadError


def test_deleted_source_is_settled():
    from app.services.media_processing_service import _is_nothing_to_extract

    deleted, _, _ = _errors()
    assert _is_nothing_to_extract(deleted("gone")) is True


def test_silent_recording_is_settled():
    from app.services.media_processing_service import _is_nothing_to_extract

    _, no_speech, _ = _errors()
    assert _is_nothing_to_extract(no_speech("silence")) is True


def test_a_download_failure_is_still_a_failure():
    from app.services.media_processing_service import _is_nothing_to_extract

    _, _, download = _errors()
    assert _is_nothing_to_extract(download("timed out")) is False


def test_settled_outcome_is_detected_through_the_cause_chain():
    from app.services.media_processing_service import _is_nothing_to_extract

    deleted, _, _ = _errors()
    wrapper = RuntimeError("wrapped")
    wrapper.__cause__ = deleted("gone")
    assert _is_nothing_to_extract(wrapper) is True


def test_deleted_source_gets_its_own_code_instead_of_unexpected():
    """75 messages read as "Unexpected MediaSourceDeleted" before this branch existed."""
    from app.services.media_processing_service import _error_details

    deleted, _, _ = _errors()
    code, detail = _error_details(deleted("gone"))
    assert code == "source_deleted"
    assert "Unexpected" not in detail


@pytest.mark.parametrize("name", ["PENDING", "QUEUED", "PROCESSING", "READY", "FAILED"])
def test_skipped_joins_the_existing_statuses(name):
    from app.models.message import MediaProcessingStatus

    assert hasattr(MediaProcessingStatus, name)
    assert MediaProcessingStatus.SKIPPED == "skipped"
