"""Tests for app.services.stt — transcription with retry logic (mocked httpx)."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.stt import transcribe


class TestTranscribe:
    """transcribe: ElevenLabs Scribe v2 STT via httpx."""

    # ── Helpers to build mock HTTP responses ─────────────────────────

    @staticmethod
    def _mock_success(text: str = "hello world") -> MagicMock:
        """Return a mock httpx.Response with a successful JSON payload."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"text": text}
        return resp

    @staticmethod
    def _mock_failure(status_code: int = 500) -> MagicMock:
        """Return a mock httpx.Response that raises on raise_for_status."""
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
        return resp

    @staticmethod
    def _mock_empty_transcript() -> MagicMock:
        """Return a mock httpx.Response with empty text."""
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"text": ""}
        return resp

    # ── Tests ────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_transcribe_success(self):
        """Valid audio → returns transcribed text."""
        with patch("app.services.stt.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            mock_post = AsyncMock()
            mock_post.return_value = self._mock_success("hello world")
            instance.post = mock_post

            result = await transcribe(b"audio data", "en")
            assert result == "hello world"

    @pytest.mark.asyncio
    async def test_transcribe_retries_on_failure(self):
        """First attempt fails, second succeeds → returns text after retry."""
        with patch("app.services.stt.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            mock_post = AsyncMock()
            mock_post.side_effect = [
                self._mock_failure(500),       # first attempt fails
                self._mock_success("retried"),  # second attempt succeeds
            ]
            instance.post = mock_post

            result = await transcribe(b"audio data", "en")
            assert result == "retried"
            assert mock_post.call_count == 2

    @pytest.mark.asyncio
    async def test_transcribe_falls_through_after_max_retries(self):
        """Both attempts fail → returns empty string."""
        with patch("app.services.stt.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            mock_post = AsyncMock()
            mock_post.side_effect = [
                self._mock_failure(500),
                self._mock_failure(503),
            ]
            instance.post = mock_post

            result = await transcribe(b"audio data", "en")
            assert result == ""
            assert mock_post.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_audio_returns_empty(self):
        """Empty audio bytes → returns '' without making any HTTP call."""
        with patch("app.services.stt.httpx.AsyncClient") as mock_client:
            result = await transcribe(b"", "en")
            assert result == ""
            mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_api_key_returns_empty(self):
        """Missing API key → returns '' without making any HTTP call."""
        with patch("app.services.stt.httpx.AsyncClient") as mock_client:
            with patch("app.services.stt.get_settings") as mock_settings:
                mock_settings.return_value.elevenlabs_api_key = ""
                mock_settings.return_value.stt_timeout_seconds = 30.0
                result = await transcribe(b"audio data", "en")
                assert result == ""
                mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_transcript_retries(self):
        """First attempt returns empty transcript → retry."""
        with patch("app.services.stt.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            mock_post = AsyncMock()
            mock_post.side_effect = [
                self._mock_empty_transcript(),
                self._mock_success("got it"),
            ]
            instance.post = mock_post

            result = await transcribe(b"audio data", "en")
            assert result == "got it"
            assert mock_post.call_count == 2

    @pytest.mark.asyncio
    async def test_both_empty_transcripts_returns_empty(self):
        """Both attempts return empty transcript → returns ''."""
        with patch("app.services.stt.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            mock_post = AsyncMock()
            mock_post.side_effect = [
                self._mock_empty_transcript(),
                self._mock_empty_transcript(),
            ]
            instance.post = mock_post

            result = await transcribe(b"audio data", "en")
            assert result == ""
            assert mock_post.call_count == 2

    @pytest.mark.asyncio
    async def test_language_code_mapping_used(self):
        """Internal language code is mapped to Scribe-compatible code."""
        with patch("app.services.stt.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            mock_post = AsyncMock()
            mock_post.return_value = self._mock_success("hola")
            instance.post = mock_post

            result = await transcribe(b"audio data", "es")
            assert result == "hola"
            # Verify language_code was passed in the data payload
            _, kwargs = mock_post.call_args
            assert kwargs["data"].get("language_code") == "es"
