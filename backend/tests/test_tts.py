"""Tests for app.services.tts — speed conversion, voice options, edge cases,
and annotation stripping (generic cleanup only — romanization logic removed).
"""

import base64
from unittest.mock import AsyncMock, patch

import pytest
from app.services.tts import (
    SPEED_MAP,
    _speed_to_edge_rate,
    strip_annotations,
    synthesize,
    voice_options,
)


# ── Speed per level ──────────────────────────────────────────────────────

def test_speed_map_all_levels_at_1x():
    """User-directed 2026-08-03: every level speaks at natural 1x speed."""
    assert SPEED_MAP == {"beginner": 1.0, "intermediate": 1.0, "fluent": 1.0}


# ── _speed_to_edge_rate ──────────────────────────────────────────────────

class TestSpeedToEdgeRate:
    """_speed_to_edge_rate: float speed → edge-tts rate string."""

    @pytest.mark.parametrize("speed,expected", [
        (0.7, "-30%"),
        (1.0, "+0%"),
        (1.5, "+50%"),
        (0.5, "-50%"),
        (0.9, "-10%"),
        (1.1, "+10%"),
        (0.0, "-100%"),
        (2.0, "+100%"),
        (0.75, "-25%"),
    ])
    def test_speed_to_rate(self, speed: float, expected: str):
        """Parametrized: various speed levels → correct percentage string."""
        assert _speed_to_edge_rate(speed) == expected


# ── voice_options ────────────────────────────────────────────────────────

class TestVoiceOptions:
    """voice_options: edge-tts is the primary provider for EVERY language."""

    @pytest.mark.parametrize("language", ["ar", "fr", "es", "yue", "zh", "en"])
    def test_all_languages_return_edge_voice(self, language):
        """Every language — including former ElevenLabs-only ones — gets an
        edge-tts voice."""
        options = voice_options(language)
        assert len(options) >= 1
        for opt in options:
            assert "voice_id" in opt
            assert "name" in opt
            assert opt["provider"] == "edge"

    def test_unknown_language_returns_edge_fallback(self):
        """Language not in the voice map → en-US edge voice as fallback."""
        options = voice_options("xx")  # Unknown language code
        assert len(options) >= 1
        for opt in options:
            assert opt["provider"] == "edge"
            assert "voice_id" in opt
            assert "name" in opt

    def test_each_option_voice_id_is_in_edge_map(self):
        """Every option's voice_id appears in EDGE_TTS_VOICES."""
        from app.services.tts import EDGE_TTS_VOICES
        for language in ["ar", "fr", "es", "yue", "zh", "en", "xx"]:
            for opt in voice_options(language):
                assert opt["provider"] == "edge"
                assert opt["voice_id"] in EDGE_TTS_VOICES.values()


# ── strip_annotations ─────────────────────────────────────────────────

class TestStripAnnotations:
    """Generic annotation stripping: parens/brackets removed, romanization
    and alphanumeric words preserved (romanization logic was removed)."""

    @pytest.mark.parametrize("raw,expected", [
        ("Hello (informal)", "Hello"),
        ("[laughs] hi", "hi"),
        ("Let's start with nei5 hou2", "Let's start with nei5 hou2"),
        ("iPhone15 is out (really)", "iPhone15 is out"),
        ("a  b  c", "a b c"),
        ("wait , really ?", "wait, really?"),
        ("  spaced   out  ", "spaced out"),
    ])
    def test_strips_or_preserves(self, raw, expected):
        assert strip_annotations(raw) == expected


# ── synthesize provider order ─────────────────────────────────────────

class TestSynthesizeProviderOrder:
    """Edge-TTS is tried FIRST for every language; ElevenLabs is only a
    fallback when edge fails."""

    @patch("app.services.tts._synthesize_edge")
    def test_edge_used_first_even_with_elevenlabs_key(self, mock_edge):
        """French (formerly ElevenLabs-only) synthesizes via edge-tts when
        the ElevenLabs key is present — edge wins."""
        import asyncio

        async def fake_edge(language, text, speed):
            return "EDGE_B64"

        mock_edge.side_effect = fake_edge
        with patch(
            "app.services.tts._synthesize_eleven",
            side_effect=AssertionError("eleven must not run first for non-primary"),
        ):
            result = asyncio.run(synthesize("Bonjour", language="fr"))
        assert result == "EDGE_B64"
        assert mock_edge.called

    def test_edge_failure_falls_back_to_elevenlabs(self):
        """If edge fails and an ElevenLabs key is set, the ElevenLabs chain
        runs; if that fails too, edge is retried then RuntimeError."""
        import asyncio
        from types import SimpleNamespace

        async def fake_edge(language, text, speed):
            raise RuntimeError("edge down")

        edge_patcher = patch("app.services.tts._synthesize_edge", side_effect=fake_edge)
        client_patcher = patch("app.services.tts.httpx.AsyncClient")

        with edge_patcher, client_patcher as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=SimpleNamespace(
                    raise_for_status=lambda: None, content=b"ELEVEN"
                )
            )
            # settings with an ElevenLabs key (test env provides it)
            from app.config import get_settings

            assert get_settings().elevenlabs_api_key == "test-key"
            result = asyncio.run(synthesize("Bonjour", language="fr"))
        assert result == base64.b64encode(b"ELEVEN").decode("utf-8")


# ── synthesize: ElevenLabs-primary languages ───────────────────────────

class TestElevenLabsPrimaryLanguages:
    """Languages in ELEVENLABS_PRIMARY_LANGUAGES use ElevenLabs FIRST;
    edge-tts becomes the fallback for those languages."""

    @staticmethod
    def _settings(monkeypatch, primary: str = "", key: str = "test-key"):
        """Mutate the cached settings instance (monkeypatch auto-restores)."""
        from app.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "elevenlabs_primary_languages", primary)
        monkeypatch.setattr(settings, "elevenlabs_api_key", key)
        return settings

    @pytest.mark.parametrize("language", ["yue", "zh", "zh-TW"])
    def test_primary_language_calls_elevenlabs_first(self, monkeypatch, language):
        """ElevenLabs is tried before edge for a primary language."""
        import asyncio

        self._settings(monkeypatch, primary="yue,zh,zh-TW")

        async def fake_eleven(text, language_, voice_id):
            return "ELEVEN_B64"

        async def fake_edge(language_, text, speed):
            raise AssertionError("edge must not be tried before ElevenLabs")

        with (
            patch("app.services.tts._synthesize_eleven", side_effect=fake_eleven),
            patch("app.services.tts._synthesize_edge", side_effect=fake_edge),
        ):
            result = asyncio.run(synthesize("你好", language=language))
        assert result == "ELEVEN_B64"

    def test_primary_language_falls_back_to_edge(self, monkeypatch):
        """ElevenLabs failure → edge-tts takes over for a primary language."""
        import asyncio

        self._settings(monkeypatch, primary="yue")

        async def fake_eleven(text, language_, voice_id):
            raise RuntimeError("eleven down")

        async def fake_edge(language_, text, speed):
            return "EDGE_B64"

        with (
            patch("app.services.tts._synthesize_eleven", side_effect=fake_eleven),
            patch("app.services.tts._synthesize_edge", side_effect=fake_edge),
        ):
            result = asyncio.run(synthesize("你好", language="yue"))
        assert result == "EDGE_B64"

    def test_primary_language_without_key_uses_edge(self, monkeypatch):
        """No ElevenLabs key → a primary language silently uses edge-tts."""
        import asyncio

        self._settings(monkeypatch, primary="yue", key="")

        async def fake_edge(language_, text, speed):
            return "EDGE_B64"

        with (
            patch("app.services.tts._synthesize_edge", side_effect=fake_edge),
            patch(
                "app.services.tts._synthesize_eleven",
                side_effect=AssertionError("ElevenLabs must not run without a key"),
            ),
        ):
            result = asyncio.run(synthesize("你好", language="yue"))
        assert result == "EDGE_B64"

    def test_non_primary_language_still_edge_first(self, monkeypatch):
        """fr is NOT primary → edge still wins (existing behavior intact)."""
        import asyncio

        self._settings(monkeypatch, primary="yue")

        async def fake_edge(language_, text, speed):
            return "EDGE_B64"

        with (
            patch("app.services.tts._synthesize_edge", side_effect=fake_edge) as mock_edge,
            patch(
                "app.services.tts._synthesize_eleven",
                side_effect=AssertionError("eleven must not run first for non-primary"),
            ),
        ):
            result = asyncio.run(synthesize("Bonjour", language="fr"))
        assert result == "EDGE_B64"
        assert mock_edge.called

    def test_primary_language_both_providers_down_raises(self, monkeypatch):
        """ElevenLabs fails AND the edge fallback fails → RuntimeError
        naming both providers."""
        import asyncio

        self._settings(monkeypatch, primary="yue")

        async def fake_eleven(text, language_, voice_id):
            raise RuntimeError("eleven down")

        async def fake_edge(language_, text, speed):
            raise RuntimeError("edge down")

        with (
            patch("app.services.tts._synthesize_eleven", side_effect=fake_eleven),
            patch("app.services.tts._synthesize_edge", side_effect=fake_edge),
        ):
            with pytest.raises(RuntimeError, match="eleven down.*edge fallback: edge down"):
                asyncio.run(synthesize("你好", language="yue"))

    def test_primary_language_no_key_edge_down_raises(self, monkeypatch):
        """No key + edge down for a primary language → wrapped RuntimeError."""
        import asyncio

        self._settings(monkeypatch, primary="yue", key="")

        async def fake_edge(language_, text, speed):
            raise RuntimeError("edge down")

        with patch("app.services.tts._synthesize_edge", side_effect=fake_edge):
            with pytest.raises(RuntimeError, match="TTS failed for yue"):
                asyncio.run(synthesize("你好", language="yue"))

    def test_voice_options_reports_elevenlabs_for_primary(self, monkeypatch):
        """/api/voices returns the ElevenLabs voice for a primary language."""
        self._settings(monkeypatch, primary="yue,zh")
        yue_opts = voice_options("yue")
        assert yue_opts[0]["provider"] == "elevenlabs"
        assert yue_opts[0]["voice_id"] == "Ys8vLfYx46rM7GaqQVf5"  # Lucky Chan
        # Non-primary languages keep their edge voice
        assert voice_options("fr")[0]["provider"] == "edge"


# ── settings: ELEVENLABS_PRIMARY_LANGUAGES parsing ─────────────────────

def test_primary_languages_parsing():
    """Comma-separated env value → set of language codes (whitespace-safe)."""
    from app.config import Settings

    assert Settings(elevenlabs_primary_languages="yue, zh,zh-TW").elevenlabs_primary_set == {
        "yue", "zh", "zh-TW",
    }
    assert Settings(elevenlabs_primary_languages="").elevenlabs_primary_set == set()
