from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMediaInfo:
    def test_voice_attribute_wins_over_generic_document_filename(self):
        from app.services.media_content_service import get_media_info

        message = SimpleNamespace(
            media=SimpleNamespace(
                document=SimpleNamespace(
                    mime_type="audio/ogg",
                    size=1234,
                    attributes=[
                        SimpleNamespace(voice=True, duration=17),
                        SimpleNamespace(file_name="voice.ogg"),
                    ],
                )
            )
        )

        info = get_media_info(message)

        assert info.media_type == "voice"
        assert info.file_name == "voice.ogg"
        assert info.mime_type == "audio/ogg"
        assert info.file_size == 1234
        assert info.duration_seconds == 17

    @pytest.mark.parametrize(
        ("mime_type", "expected"),
        [
            ("audio/mpeg", "audio"),
            ("video/mp4", "video"),
            ("image/png", "photo"),
            ("application/pdf", "document"),
        ],
    )
    def test_document_category_uses_mime_type(self, mime_type, expected):
        from app.services.media_content_service import get_media_info

        message = SimpleNamespace(
            media=SimpleNamespace(
                document=SimpleNamespace(
                    mime_type=mime_type,
                    size=99,
                    attributes=[SimpleNamespace(file_name="sample.bin")],
                )
            )
        )

        assert get_media_info(message).media_type == expected


class TestChunkText:
    def test_chunks_long_content_without_losing_text(self):
        from app.services.media_content_service import chunk_text

        text = "\n\n".join(f"Paragraph {index}: " + ("x" * 80) for index in range(40))
        chunks = chunk_text(text, max_chars=500, overlap_chars=0)

        assert len(chunks) > 1
        assert all(len(chunk) <= 500 for chunk in chunks)
        assert "\n\n".join(chunks) == text


class TestDeepgramTranscription:
    async def test_uses_only_search_focused_nova3_parameters(self, tmp_path):
        from app.services.media_content_service import transcribe_media_file

        media_path = tmp_path / "voice.ogg"
        media_path.write_bytes(b"audio bytes")

        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "results": {
                "channels": [{"alternatives": [{"transcript": "Привет, мир."}]}]
            }
        }
        client = AsyncMock()
        client.post.return_value = response

        with (
            patch("app.services.media_content_service.settings") as mock_settings,
            patch(
                "app.services.media_content_service.httpx.AsyncClient"
            ) as client_class,
        ):
            mock_settings.deepgram_api_key = "test-key"
            mock_settings.deepgram_model = "nova-3"
            mock_settings.deepgram_language = "multi"
            client_class.return_value.__aenter__.return_value = client

            transcript = await transcribe_media_file(media_path, "audio/ogg")

        assert transcript == "Привет, мир."
        request = client.post.await_args
        assert request.kwargs["params"] == {
            "model": "nova-3",
            "language": "multi",
            "smart_format": "true",
        }
        assert "diarize" not in request.kwargs["params"]
        assert "utterances" not in request.kwargs["params"]
        assert "detect_language" not in request.kwargs["params"]
        assert "punctuate" not in request.kwargs["params"]
        assert request.kwargs["headers"]["Content-Type"] == "audio/ogg"

    async def test_missing_deepgram_key_is_explicit_failure(self, tmp_path):
        from app.services.media_content_service import (
            MediaProcessingConfigurationError,
            transcribe_media_file,
        )

        media_path = tmp_path / "voice.ogg"
        media_path.write_bytes(b"audio bytes")

        with patch("app.services.media_content_service.settings") as mock_settings:
            mock_settings.deepgram_api_key = ""
            with pytest.raises(
                MediaProcessingConfigurationError,
                match="DEEPGRAM_API_KEY",
            ):
                await transcribe_media_file(media_path, "audio/ogg")

    async def test_empty_provider_transcript_is_failure(self, tmp_path):
        from app.services.media_content_service import (
            MediaProviderResponseError,
            transcribe_media_file,
        )

        media_path = tmp_path / "voice.ogg"
        media_path.write_bytes(b"audio bytes")

        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"results": {"channels": []}}
        client = AsyncMock()
        client.post.return_value = response

        with (
            patch("app.services.media_content_service.settings") as mock_settings,
            patch(
                "app.services.media_content_service.httpx.AsyncClient"
            ) as client_class,
        ):
            mock_settings.deepgram_api_key = "test-key"
            mock_settings.deepgram_model = "nova-3"
            mock_settings.deepgram_language = "multi"
            client_class.return_value.__aenter__.return_value = client

            with pytest.raises(
                MediaProviderResponseError,
                match="empty transcript",
            ):
                await transcribe_media_file(media_path, "audio/ogg")


class TestOpenAISummaries:
    async def test_summary_uses_available_cost_optimized_gpt56_model(self):
        from app.services.media_content_service import ContentSummary, summarize_text

        parsed = ContentSummary(summary="Краткое содержание.")
        output_item = SimpleNamespace(
            type="message",
            content=[SimpleNamespace(type="output_text", parsed=parsed)],
        )
        response = SimpleNamespace(output=[output_item])
        client = SimpleNamespace(
            responses=SimpleNamespace(parse=AsyncMock(return_value=response))
        )

        with (
            patch("app.services.media_content_service.settings") as mock_settings,
            patch(
                "app.services.media_content_service.get_openai_client",
                new_callable=AsyncMock,
                return_value=client,
            ),
        ):
            mock_settings.media_summary_model = "gpt-5.6-luna"
            mock_settings.media_summary_chunk_chars = 120_000
            result = await summarize_text("Полный текст")

        assert result == "Краткое содержание."
        request = client.responses.parse.await_args.kwargs
        assert request["model"] == "gpt-5.6-luna"
        assert request["reasoning"] == {"effort": "none"}
        assert request["store"] is False
        assert request["text_format"] is ContentSummary

    async def test_image_analysis_uses_low_detail_and_structured_output(self, tmp_path):
        from app.services.media_content_service import ImageAnalysis, analyze_image

        image_path = tmp_path / "photo.jpg"
        image_path.write_bytes(b"jpeg")
        parsed = ImageAnalysis(
            visible_text="WAI",
            summary="Логотип WAI на светлом фоне.",
        )
        output_item = SimpleNamespace(
            type="message",
            content=[SimpleNamespace(type="output_text", parsed=parsed)],
        )
        response = SimpleNamespace(output=[output_item])
        client = SimpleNamespace(
            responses=SimpleNamespace(parse=AsyncMock(return_value=response))
        )

        with (
            patch("app.services.media_content_service.settings") as mock_settings,
            patch(
                "app.services.media_content_service.get_openai_client",
                new_callable=AsyncMock,
                return_value=client,
            ),
        ):
            mock_settings.media_summary_model = "gpt-5.6-luna"
            mock_settings.media_image_max_output_tokens = 1600
            result = await analyze_image(image_path, "image/jpeg")

        assert result == parsed
        request = client.responses.parse.await_args.kwargs
        assert request["input"][0]["role"] == "developer"
        image_input = request["input"][1]["content"][1]
        assert image_input["type"] == "input_image"
        assert image_input["detail"] == "low"
        assert request["reasoning"] == {"effort": "none"}
        assert request["max_output_tokens"] == 1600

    async def test_invalid_structured_image_response_is_provider_error(self, tmp_path):
        from pydantic import ValidationError

        from app.services.media_content_service import (
            ImageAnalysis,
            MediaProviderResponseError,
            analyze_image,
        )

        image_path = tmp_path / "photo.jpg"
        image_path.write_bytes(b"jpeg")
        try:
            ImageAnalysis.model_validate_json('{"visible_text":"truncated')
        except ValidationError as validation_error:
            error = validation_error

        client = SimpleNamespace(
            responses=SimpleNamespace(parse=AsyncMock(side_effect=error))
        )
        with (
            patch("app.services.media_content_service.settings") as mock_settings,
            patch(
                "app.services.media_content_service.get_openai_client",
                new_callable=AsyncMock,
                return_value=client,
            ),
        ):
            mock_settings.media_summary_model = "gpt-5.6-luna"
            mock_settings.media_image_max_output_tokens = 1600
            with pytest.raises(
                MediaProviderResponseError,
                match="invalid structured image",
            ):
                await analyze_image(image_path, "image/jpeg")


class TestDocumentExtraction:
    async def test_plain_text_document_is_extracted_as_searchable_text(self, tmp_path):
        from app.services.media_content_service import extract_document_text

        source = tmp_path / "notes.txt"
        source.write_text("# Заголовок\n\nПолный текст.", encoding="utf-8")

        result = await extract_document_text(source)

        assert "# Заголовок" in result
        assert "Полный текст." in result
