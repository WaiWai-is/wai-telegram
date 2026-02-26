from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.transcription_service import (
    MAX_AUDIO_BYTES,
    download_and_transcribe,
    transcribe_audio,
)


class TestTranscribeAudio:
    async def test_transcribe_success(self):
        mock_response = MagicMock()
        mock_channel = MagicMock()
        mock_alt = MagicMock()
        mock_alt.transcript = "Hello world"
        mock_channel.alternatives = [mock_alt]
        mock_response.results.channels = [mock_channel]

        with patch("app.services.transcription_service.settings") as mock_settings:
            mock_settings.deepgram_api_key = "test-key"
            mock_settings.deepgram_model = "nova-3"
            with patch("deepgram.AsyncDeepgramClient") as mock_dg_cls:
                mock_dg = AsyncMock()
                mock_dg.listen.v1.media.transcribe_file = AsyncMock(return_value=mock_response)
                mock_dg_cls.return_value = mock_dg

                result = await transcribe_audio(b"audio data")
                assert result == "Hello world"

    async def test_transcribe_empty_channels(self):
        mock_response = MagicMock()
        mock_response.results.channels = []

        with patch("app.services.transcription_service.settings") as mock_settings:
            mock_settings.deepgram_api_key = "test-key"
            mock_settings.deepgram_model = "nova-3"
            with patch("deepgram.AsyncDeepgramClient") as mock_dg_cls:
                mock_dg = AsyncMock()
                mock_dg.listen.v1.media.transcribe_file = AsyncMock(return_value=mock_response)
                mock_dg_cls.return_value = mock_dg

                result = await transcribe_audio(b"audio data")
                assert result == ""


class TestDownloadAndTranscribe:
    async def test_no_deepgram_key(self):
        with patch("app.services.transcription_service.settings") as mock_settings:
            mock_settings.deepgram_api_key = ""
            result = await download_and_transcribe(MagicMock(), MagicMock())
            assert result is None

    async def test_empty_audio(self):
        mock_client = AsyncMock()
        mock_client.download_media = AsyncMock(return_value=None)

        mock_message = MagicMock()
        mock_message.id = 1

        with patch("app.services.transcription_service.settings") as mock_settings:
            mock_settings.deepgram_api_key = "test-key"
            # download_media writes to the buffer; simulate empty buffer
            async def fake_download(msg, file):
                pass  # leave buffer empty

            mock_client.download_media = fake_download
            result = await download_and_transcribe(mock_client, mock_message)
            assert result is None

    async def test_audio_too_large(self):
        mock_message = MagicMock()
        mock_message.id = 1

        mock_client = AsyncMock()

        async def fake_download(msg, file):
            file.write(b"x" * (MAX_AUDIO_BYTES + 1))

        mock_client.download_media = fake_download

        with patch("app.services.transcription_service.settings") as mock_settings:
            mock_settings.deepgram_api_key = "test-key"
            result = await download_and_transcribe(mock_client, mock_message)
            assert result is None

    async def test_success(self):
        mock_message = MagicMock()
        mock_message.id = 1

        mock_client = AsyncMock()

        async def fake_download(msg, file):
            file.write(b"audio data here")

        mock_client.download_media = fake_download

        with patch("app.services.transcription_service.settings") as mock_settings, \
             patch("app.services.transcription_service.transcribe_audio", new_callable=AsyncMock, return_value="Transcribed text"):
            mock_settings.deepgram_api_key = "test-key"
            result = await download_and_transcribe(mock_client, mock_message)
            assert result == "Transcribed text"
