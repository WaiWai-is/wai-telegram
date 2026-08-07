"""Tests for Bot API media handling without size limits or RAM buffering."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent.media_processor import (
    _download_telegram_file,
    describe_photo,
    extract_document_text,
    process_bot_media,
    transcribe_bot_voice,
)


async def _write_download(_file_id, destination):
    destination.write_bytes(b"fixture")
    return destination


async def test_document_uses_full_markitdown_extraction():
    with (
        patch(
            "app.services.agent.media_processor._download_telegram_file",
            new_callable=AsyncMock,
            side_effect=_write_download,
        ) as download,
        patch(
            "app.services.agent.media_processor.extract_local_document",
            new_callable=AsyncMock,
            return_value="Full extracted document",
        ) as extract,
    ):
        result = await extract_document_text("file-1", "report.pdf")

    assert result == "Full extracted document"
    assert download.await_args.args[1].name == "report.pdf"
    extract.assert_awaited_once()


async def test_document_failure_is_explicit():
    with patch(
        "app.services.agent.media_processor._download_telegram_file",
        new_callable=AsyncMock,
        side_effect=RuntimeError("local bot api unavailable"),
    ):
        with pytest.raises(RuntimeError, match="local bot api unavailable"):
            await extract_document_text("file-1", "report.pdf")


async def test_photo_uses_shared_high_detail_analysis():
    analysis = SimpleNamespace(summary="Photo summary", visible_text="Visible text")
    with (
        patch(
            "app.services.agent.media_processor._download_telegram_file",
            new_callable=AsyncMock,
            side_effect=_write_download,
        ),
        patch(
            "app.services.agent.media_processor.analyze_image",
            new_callable=AsyncMock,
            return_value=analysis,
        ) as analyze,
    ):
        result = await describe_photo("photo-1")

    assert result == "Photo summary\n\nVisible text"
    analyze.assert_awaited_once()


async def test_bot_media_download_delegates_to_streaming_local_client(tmp_path):
    destination = tmp_path / "large.bin"
    bot_client = AsyncMock()
    bot_client.download_file_to.return_value = destination
    with patch(
        "app.services.agent.media_processor.get_bot_api_client",
        return_value=bot_client,
    ):
        result = await _download_telegram_file("large-file", destination)

    assert result == destination
    bot_client.download_file_to.assert_awaited_once_with("large-file", destination)


def test_agent_media_has_no_application_download_limit():
    import inspect
    import app.services.agent.media_processor as media_processor

    source = inspect.getsource(media_processor)
    assert "MAX_DOWNLOAD_SIZE" not in source
    assert "api.telegram.org" not in source


async def test_bot_video_uses_full_shared_media_pipeline(tmp_path):
    processed = SimpleNamespace(
        content_summary="Video summary", content_text="Transcript"
    )
    with (
        patch(
            "app.services.agent.media_processor._download_telegram_file",
            new_callable=AsyncMock,
            side_effect=_write_download,
        ),
        patch(
            "app.services.agent.media_processor.process_local_media",
            new_callable=AsyncMock,
            return_value=processed,
        ) as process,
    ):
        result = await process_bot_media(
            "video-file",
            media_type="video",
            file_name="clip.mp4",
            mime_type="video/mp4",
            duration_seconds=60,
        )

    assert result is processed
    assert process.await_args.args[1:] == ("video", "video/mp4", 60)


async def test_all_production_bot_downloads_use_media_volume(tmp_path):
    destinations = []

    async def capture_download(_file_id, destination):
        destinations.append(destination)
        destination.write_bytes(b"fixture")
        return destination

    processed = SimpleNamespace(content_summary="summary", content_text="text")
    analysis = SimpleNamespace(summary="photo", visible_text=None)
    production_settings = SimpleNamespace(
        environment="production",
        media_root=tmp_path,
    )
    with (
        patch("app.services.agent.media_processor.settings", production_settings),
        patch(
            "app.services.agent.media_processor._download_telegram_file",
            new_callable=AsyncMock,
            side_effect=capture_download,
        ),
        patch(
            "app.services.agent.media_processor.analyze_image",
            new_callable=AsyncMock,
            return_value=analysis,
        ),
        patch(
            "app.services.agent.media_processor.extract_local_document",
            new_callable=AsyncMock,
            return_value="document",
        ),
        patch(
            "app.services.agent.media_processor.process_local_media",
            new_callable=AsyncMock,
            return_value=processed,
        ),
        patch(
            "app.services.agent.media_processor.transcribe_media_file",
            new_callable=AsyncMock,
            return_value="voice",
        ),
    ):
        await describe_photo("photo")
        await extract_document_text("document", "report.pdf")
        await process_bot_media(
            "video",
            media_type="video",
            file_name="clip.mp4",
            mime_type="video/mp4",
            duration_seconds=60,
        )
        await transcribe_bot_voice("voice")

    work_root = tmp_path / "bot-work"
    assert len(destinations) == 4
    assert all(destination.is_relative_to(work_root) for destination in destinations)


async def test_deferred_production_bot_downloads_use_ephemeral_storage(tmp_path):
    destinations = []

    async def capture_download(_file_id, destination):
        destinations.append(destination)
        destination.write_bytes(b"fixture")
        return destination

    production_settings = SimpleNamespace(
        environment="production",
        media_pipeline_enabled=False,
        media_root=tmp_path,
    )
    analysis = SimpleNamespace(summary="photo", visible_text=None)
    with (
        patch("app.services.agent.media_processor.settings", production_settings),
        patch(
            "app.services.agent.media_processor._download_telegram_file",
            new_callable=AsyncMock,
            side_effect=capture_download,
        ),
        patch(
            "app.services.agent.media_processor.analyze_image",
            new_callable=AsyncMock,
            return_value=analysis,
        ),
    ):
        await describe_photo("photo")

    assert len(destinations) == 1
    assert not destinations[0].is_relative_to(tmp_path)


class TestMediaTypes:
    def test_photo_content_type(self):
        from app.services.agent.forward_processor import parse_forwarded_message

        content = parse_forwarded_message({"photo": [{"file_id": "abc"}]})
        assert content.content_type == "photo"

    def test_document_content_type(self):
        from app.services.agent.forward_processor import parse_forwarded_message

        content = parse_forwarded_message(
            {"document": {"file_id": "abc", "file_name": "test.pdf"}}
        )
        assert content.content_type == "document"

    @pytest.mark.parametrize("media_type", ["video", "audio", "voice", "video_note"])
    def test_downloadable_media_types(self, media_type):
        from app.services.agent.forward_processor import parse_forwarded_message

        content = parse_forwarded_message({media_type: {"file_id": "abc"}})
        assert content.content_type == media_type
