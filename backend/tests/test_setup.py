"""Voice-guided setup API tests (v13.1, grandma mode v1)."""
import pytest


@pytest.fixture()
def mock_voice(monkeypatch):
    async def fake_transcribe(audio_bytes, language):
        return "three"

    async def fake_fast(messages):
        return "3"  # maps to the third option

    monkeypatch.setattr("app.services.stt.transcribe", fake_transcribe)
    monkeypatch.setattr("app.services.llm.chat_reply_fast", fake_fast)
    return None


def test_voice_setup_subject_by_number(client, mock_voice):
    r = client.post(
        "/api/setup/voice",
        data={"step": "subject", "language": "en"},
        files={"audio": ("a.webm", b"\x00\x01", "audio/webm")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unclear"] is False
    assert body["choice"] == "free-will"  # third in DISPLAY_FIRST + alpha order
    assert body["label"] == "Does Free Will Exist?"


def test_voice_setup_depth_and_style(client, mock_voice):
    r = client.post("/api/setup/voice", data={"step": "depth"}, files={"audio": ("a.webm", b"\x00", "audio/webm")})
    assert r.json()["choice"] == "fluent"  # 3 = Expert
    r = client.post("/api/setup/voice", data={"step": "style"}, files={"audio": ("a.webm", b"\x00", "audio/webm")})
    assert r.json()["choice"] == "heckler"  # 3 = Heckler


def test_voice_setup_empty_transcript_unclear(client, monkeypatch):
    async def fake_transcribe(audio_bytes, language):
        return ""

    monkeypatch.setattr("app.services.stt.transcribe", fake_transcribe)
    r = client.post("/api/setup/voice", data={"step": "subject"}, files={"audio": ("a.webm", b"\x00", "audio/webm")})
    assert r.json()["unclear"] is True


def test_voice_setup_bad_step_422(client, mock_voice):
    r = client.post("/api/setup/voice", data={"step": "nope"}, files={"audio": ("a.webm", b"\x00", "audio/webm")})
    assert r.status_code == 422


def test_host_tts_returns_audio(client, monkeypatch):
    async def fake_synthesize(text, language="en", voice_id=None, level="beginner", **kw):
        assert voice_id == "en-GB-SoniaNeural"  # host voice
        return "QUJD"

    monkeypatch.setattr("app.services.tts.synthesize", fake_synthesize)
    r = client.post("/api/setup/host", data={"text": "Welcome."})
    assert r.status_code == 200
    assert r.json()["audio_base64"] == "QUJD"
