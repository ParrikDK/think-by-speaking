"""Voices catalog API test — GET /api/voices.

Edge-TTS is the primary provider for every language.
"""
import pytest


def test_list_voices_default(client):
    """English (default): the v13 accent×gender picker + realtime presets."""
    r = client.get("/api/voices")
    assert r.status_code == 200
    voices = r.json()
    assert isinstance(voices, list)
    assert len(voices) == 8  # 6 edge (accent×gender) + 2 realtime
    assert voices[0]["voice_id"] == "en-GB-RyanNeural"  # British male default
    assert voices[0]["provider"] == "edge"
    providers = {v["provider"] for v in voices}
    assert providers == {"edge", "realtime"}


def test_voice_item_shape(client):
    r = client.get("/api/voices")
    for voice in r.json():
        assert "voice_id" in voice
        assert "name" in voice
        assert "provider" in voice


def test_voice_provider_is_string(client):
    r = client.get("/api/voices")
    for voice in r.json():
        assert isinstance(voice["voice_id"], str) and voice["voice_id"]
        assert isinstance(voice["name"], str) and voice["name"]
        assert voice["provider"] in ("edge", "elevenlabs", "realtime")


def test_voices_for_former_elevenlabs_language(client):
    """French used to be ElevenLabs-only — edge-tts serves it now."""
    r = client.get("/api/voices?language=fr")
    assert r.status_code == 200
    voices = r.json()
    assert len(voices) == 1
    assert voices[0]["provider"] == "edge"


def test_voices_for_edge_language(client):
    r = client.get("/api/voices?language=th")
    assert r.status_code == 200
    voices = r.json()
    assert len(voices) == 1
    assert voices[0]["provider"] == "edge"


def test_voices_for_unknown_language(client):
    r = client.get("/api/voices?language=xx")
    assert r.status_code == 200
    voices = r.json()
    assert len(voices) == 1


@pytest.mark.parametrize("lang", ["fr", "es", "de", "ar", "zh", "th", "yue", "xx"])  # en: picker, see test_list_voices_default
def test_voices_known_languages_all_edge(client, lang):
    r = client.get(f"/api/voices?language={lang}")
    assert r.status_code == 200
    voices = r.json()
    assert len(voices) == 1
    assert voices[0]["provider"] == "edge"
