"""Chat API tests — TestClient with mocked llm/stt/tts services."""
import json

import pytest

from app.prompts.tutor import silence_message

FAKE_PAYLOAD = {
    "reply": "Bonjour ! Comment ça va ?",
    "translation": "Hello! How are you?",
    "feedback": {
        "stance": "partially_agree",
        "score": 55,
        "score_delta": 5,
        "counter": "Close — you said it right.",
        "evidence": "The verb follows je.",
        "next": "How would you answer?",
    },
}


@pytest.fixture()
def mock_services(monkeypatch):
    calls = {"stt": 0, "tts": 0, "llm": 0, "llm_stream": 0, "llm_messages": []}

    async def fake_chat_json(messages, language="en", native_language="en"):
        calls["llm"] += 1
        calls["llm_messages"].append(messages)
        return dict(FAKE_PAYLOAD)

    async def fake_chat_json_stream(messages, language="en", native_language="en"):
        calls["llm_stream"] += 1
        yield dict(FAKE_PAYLOAD)

    async def fake_transcribe(audio_bytes, language):
        calls["stt"] += 1
        return ""  # default: empty transcript (silence path)

    async def fake_synthesize(text, language="en", voice_id=None, level="beginner", **kwargs):
        calls["tts"] += 1
        return "QUJD"  # base64 of b"ABC"

    monkeypatch.setattr("app.services.llm.chat_json", fake_chat_json)
    monkeypatch.setattr("app.services.llm.chat_json_stream", fake_chat_json_stream)
    monkeypatch.setattr("app.services.stt.transcribe", fake_transcribe)
    monkeypatch.setattr("app.services.tts.synthesize", fake_synthesize)
    return calls


def _init(client, language="fr", level="beginner", **extra):
    data = {"language": language, "native_language": "en", "level": level, **extra}
    r = client.post("/api/chat/init", data=data)
    assert r.status_code == 200, r.text
    return r.json()


def test_chat_init(client, mock_services):
    body = _init(client, scenario_id="restaurant")
    assert body["session_id"]
    greeting = body["greeting"]
    assert greeting["text"] == FAKE_PAYLOAD["reply"]
    # v10: translations flow through — the mock stands in for an
    # intermediate-style payload; real beginner personas return "" by design.
    assert greeting["translation"] == FAKE_PAYLOAD["translation"]
    assert "romanization" not in greeting  # romanization feature removed
    assert greeting["audio_base64"] == "QUJD"
    assert mock_services["llm"] == 1 and mock_services["tts"] == 1


def test_init_rejects_bad_level(client, mock_services):
    r = client.post(
        "/api/chat/init",
        data={"language": "fr", "native_language": "en", "level": "A1"},
    )
    assert r.status_code == 422


def test_init_rejects_bad_language(client, mock_services):
    r = client.post(
        "/api/chat/init",
        data={"language": "xx", "native_language": "en", "level": "beginner"},
    )
    assert r.status_code == 400


def test_text_chat_turn_skips_stt(client, mock_services, monkeypatch):
    session_id = _init(client)["session_id"]
    r = client.post(
        "/api/chat",
        data={"session_id": session_id, "language": "fr", "text": "Je suis bien"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == session_id
    assert body["user_text"] == "Je suis bien"
    reply = body["reply"]
    assert reply["text"] == FAKE_PAYLOAD["reply"]
    assert reply["feedback"]["stance"] == "partially_agree"
    assert mock_services["stt"] == 0  # typed text → no STT call


def test_fillers_counted_on_spoken_turns(client, mock_services, monkeypatch):
    """Think By Speaking delivery pillar: spoken turns count fillers (um/like);
    typed turns carry none."""
    async def zh_payload(messages, language="zh", native_language="en"):
        return {
            "reply": "That is fair!",
            "translation": "That is fair!",
            "feedback": {"stance": "partially_agree", "score": 52},
        }

    monkeypatch.setattr("app.services.llm.chat_json", zh_payload)

    async def fake_transcribe(audio_bytes, language):
        return "um, like, I think that is true, you know"

    monkeypatch.setattr("app.services.stt.transcribe", fake_transcribe)
    session_id = _init(client, language="en")["session_id"]
    r = client.post(
        "/api/chat",
        data={"session_id": session_id, "language": "en"},
        files={"audio": ("audio.webm", b"\x00\x01\x02", "audio/webm")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["reply"]["feedback"]["filler_count"] == 3  # um, like, you know


def test_empty_audio_returns_localized_silence(client, mock_services):
    """Beginner level: the silence prompt is spoken in the learner's NATIVE
    language (they can't understand target-language speech yet)."""
    session_id = _init(client)["session_id"]  # beginner, native en
    r = client.post(
        "/api/chat",
        data={"session_id": session_id, "language": "fr"},
        files={"audio": ("audio.webm", b"\x00\x01\x02", "audio/webm")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_text"] == ""
    assert body["reply"]["text"] == silence_message("en")
    assert body["reply"]["feedback"] is None
    assert body["reply"]["audio_base64"] == "QUJD"
    assert mock_services["stt"] == 1


def test_empty_audio_silence_in_target_language_for_fluent(client, mock_services):
    """Fluent level: the silence prompt stays in the target language."""
    session_id = _init(client, level="fluent")["session_id"]
    r = client.post(
        "/api/chat",
        data={"session_id": session_id, "language": "fr"},
        files={"audio": ("audio.webm", b"\x00\x01\x02", "audio/webm")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["reply"]["text"] == silence_message("fr")


def test_chat_requires_audio_or_text(client, mock_services):
    session_id = _init(client)["session_id"]
    r = client.post("/api/chat", data={"session_id": session_id, "language": "fr"})
    assert r.status_code == 422


def test_chat_unknown_session_404(client, mock_services):
    r = client.post(
        "/api/chat",
        data={"session_id": "nope", "language": "fr", "text": "hi"},
    )
    assert r.status_code == 404


def test_stream_event_sequence(client, mock_services):
    session_id = _init(client)["session_id"]
    r = client.post(
        "/api/chat/stream",
        data={"session_id": session_id, "language": "fr", "text": "Bonjour"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = []
    for block in r.text.strip().split("\n\n"):
        event = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        events.append((event, data))

    kinds = [e for e, _ in events]
    assert kinds == ["complete", "audio", "done"]
    complete = next(d for e, d in events if e == "complete")
    assert complete["session_id"] == session_id
    assert complete["user_text"] == "Bonjour"
    assert complete["reply"]["text"] == FAKE_PAYLOAD["reply"]
    assert complete["reply"]["audio_base64"] == ""  # audio arrives separately
    audio = next(d for e, d in events if e == "audio")
    assert audio["audio_base64"] == "QUJD"
    assert mock_services["llm_stream"] == 1


def test_stream_empty_audio_silence(client, mock_services):
    session_id = _init(client)["session_id"]
    r = client.post(
        "/api/chat/stream",
        data={"session_id": session_id, "language": "fr"},
        files={"audio": ("audio.webm", b"\x00\x01", "audio/webm")},
    )
    assert r.status_code == 200
    kinds = [
        line[7:] for line in r.text.splitlines() if line.startswith("event: ")
    ]
    assert kinds == ["complete", "done"]
    complete_block = [
        json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")
    ][0]
    assert complete_block["user_text"] == ""
    assert complete_block["reply"]["text"] == silence_message("en")  # beginner → native language


def test_chinese_reply_not_romanized(client, mock_services, monkeypatch):
    """Chinese replies pass through raw — the romanization feature is gone."""
    async def zh_payload(messages, language="zh", native_language="en"):
        return {
            "reply": "你好！你叫什么名字？",
            "translation": "Hello! What is your name?",
            "feedback": None,
        }

    monkeypatch.setattr("app.services.llm.chat_json", zh_payload)
    body = _init(client, language="zh")
    greeting = body["greeting"]
    assert greeting["text"] == "你好！你叫什么名字？"
    assert "romanization" not in greeting


@pytest.mark.parametrize("level", ["beginner", "intermediate", "fluent"])
def test_feedback_card_raw_for_all_levels(client, mock_services, monkeypatch, level):
    """The debate card fields flow through raw at every level (v13)."""
    async def zh_payload_with_feedback(messages, language="zh", native_language="en"):
        return {
            "reply": "试着说：你好！",
            "translation": "Try saying: Hello!",
            "feedback": {
                "stance": "partially_agree",
                "score": 55,
                "score_delta": 5,
                "counter": "Partly — 你好 works for one person.",
                "evidence": "Mandarin uses 您 for respect.",
                "next": "When would you use 您?",
            },
        }

    monkeypatch.setattr("app.services.llm.chat_json", zh_payload_with_feedback)
    body = _init(client, language="zh", level=level)
    feedback = body["greeting"]["feedback"]
    assert feedback is not None
    assert feedback["score"] == 55
    assert feedback["stance"] == "partially_agree"


def test_llm_history_contains_raw_reply(client, mock_services, monkeypatch):
    """Stored replies flow back to the LLM as raw text — display romanization
    is gone, so history fed to the model is clean (no pinyin-annotated text)."""
    async def zh_payload(messages, language="zh", native_language="en"):
        mock_services["llm_messages"].append(messages)
        return {
            "reply": "你好！你叫什么名字？",
            "translation": "Hello! What is your name?",
            "feedback": None,
        }

    monkeypatch.setattr("app.services.llm.chat_json", zh_payload)
    session_id = _init(client, language="zh")["session_id"]

    r = client.post(
        "/api/chat",
        data={"session_id": session_id, "language": "zh", "text": "你好"},
    )
    assert r.status_code == 200, r.text

    # Second chat_json call (the turn) carries the stored greeting in history
    assert len(mock_services["llm_messages"]) == 2
    history = mock_services["llm_messages"][1]
    assistant_entries = [m for m in history if m.get("role") == "assistant"]
    assert any(m["content"] == "你好！你叫什么名字？" for m in assistant_entries)


# ── Error-path tests ──────────────────────────────────────────────


def test_chat_tts_failure_returns_tts_failure_error(client, mock_services, monkeypatch):
    """When tts.synthesize fails, response has error_type='tts_failure'
    and empty audio_base64."""
    async def broken_synthesize(*args, **kwargs):
        raise RuntimeError("TTS provider unavailable")

    monkeypatch.setattr("app.services.tts.synthesize", broken_synthesize)

    session_id = _init(client)["session_id"]
    r = client.post(
        "/api/chat",
        data={"session_id": session_id, "language": "fr", "text": "Bonjour"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error_type"] == "tts_failure"
    assert body["reply"]["audio_base64"] == ""
    # Non-audio fields are still populated
    assert body["reply"]["text"] is not None


def test_chat_llm_fallback_nonstreaming(client, monkeypatch):
    """When LLM fails in the non-streaming path, the fallback payload
    (error_message) is returned instead of crashing."""
    async def fake_synth(*args, **kwargs):
        return "QUJD"

    async def fake_trans(*args, **kwargs):
        return ""

    monkeypatch.setattr("app.services.tts.synthesize", fake_synth)
    monkeypatch.setattr("app.services.stt.transcribe", fake_trans)

    # Patch _complete_once (the internal function that chat_json wraps with retry)
    async def broken_complete(messages):
        raise RuntimeError("LLM failed after 3 attempts")

    monkeypatch.setattr("app.services.llm._complete_once", broken_complete)

    session_id = _init(client)["session_id"]

    r = client.post(
        "/api/chat",
        data={"session_id": session_id, "language": "fr", "text": "Bonjour"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    from app.prompts.tutor import error_message

    assert body["reply"]["text"] == error_message("fr")


def test_chat_tts_endpoint(client, mock_services):
    """POST /api/chat/tts returns audio_base64 for a given session/text."""
    session_id = _init(client)["session_id"]
    r = client.post(
        "/api/chat/tts",
        data={
            "session_id": session_id,
            "text": "Bonjour tout le monde",
            "language": "fr",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["audio_base64"] == "QUJD"


def test_stream_llm_failure_uses_fallback(client, monkeypatch):
    """When chat_json_stream fails, the SSE complete event carries the
    fallback payload and error_type='llm_failure'."""
    async def fake_synth(*args, **kwargs):
        return "QUJD"

    async def fake_trans(*args, **kwargs):
        return ""

    monkeypatch.setattr("app.services.tts.synthesize", fake_synth)
    monkeypatch.setattr("app.services.stt.transcribe", fake_trans)

    # A failing streaming LLM — empty async generator (no yields)
    async def broken_stream(messages, language="en", native_language="en"):
        if False:
            yield  # makes this an async generator that yields nothing

    monkeypatch.setattr("app.services.llm.chat_json_stream", broken_stream)

    session_id = _init(client)["session_id"]
    r = client.post(
        "/api/chat/stream",
        data={"session_id": session_id, "language": "fr", "text": "Bonjour"},
    )
    assert r.status_code == 200, r.text

    events = []
    for block in r.text.strip().split("\n\n"):
        event = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        events.append((event, data))

    kinds = [e for e, _ in events]
    assert kinds == ["complete", "audio", "done"]

    complete = next(d for e, d in events if e == "complete")
    assert complete["error_type"] == "llm_failure"

    from app.prompts.tutor import error_message

    assert complete["reply"]["text"] == error_message("fr")


# ── Language-mismatch guard ─────────────────────────────────────────────

from app.routers.chat import _reply_language_mismatch, _script_ratio


def test_script_ratio():
    assert _script_ratio("Hello world") == 0.0
    assert _script_ratio("你好世界") == 1.0
    assert _script_ratio("Hello 你好 world") == pytest.approx(2 / 12)  # 2 CJK of 12 letters


@pytest.mark.parametrize("level,user,reply,expected", [
    # intermediate/fluent mirror the learner's script
    ("intermediate", "How do you say X in Cantonese?", "你可以話「X」。", True),
    ("fluent", "Can you explain in English?", "早晨呀！今日過得點呀？", True),
    ("intermediate", "我今日好開心", "Great to hear that!", True),
    # matching scripts → no retry
    ("intermediate", "How do you say X?", "You can say 你好.", False),
    # teaching replies embed the target phrase in a native sentence — not a mismatch
    ("intermediate", "How do I say I'm happy?", "You can say 我今日好開心.", False),
    ("intermediate", "我今日好開心", "嘩，咁開心！", False),
    # beginner always teaches in the native language — never guarded
    ("beginner", "你好", "Hello! Today we learn 你好.", False),
])
def test_reply_language_mismatch(level, user, reply, expected):
    assert _reply_language_mismatch(level, user, reply) is expected


def test_nudge_retry_uses_corrected_reply(client, mock_services, monkeypatch):
    """English question → Cantonese reply: the guard regenerates the reply
    once (cheap reply-only call) and the corrected English reply wins."""
    async def cjk_reply(messages, language="fr", native_language="en"):
        return {"reply": "你可以話「我今日好開心」。", "translation": "",
                "feedback": None}

    async def english_nudge(messages, language="fr"):
        assert "IMPORTANT: answer in the SAME language" in messages[-1]["content"]
        return "You can say 我今日好開心 — meaning I'm very happy today."

    monkeypatch.setattr("app.services.llm.chat_json", cjk_reply)
    monkeypatch.setattr("app.services.llm.chat_reply_fast", english_nudge)
    session_id = _init(client, level="intermediate")["session_id"]
    r = client.post(
        "/api/chat",
        data={"session_id": session_id, "language": "fr", "text": "How do I say I'm happy?"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["reply"]["text"].startswith("You can say")


def test_nudge_retry_not_called_when_reply_matches(client, mock_services, monkeypatch):
    """Matching-language replies skip the retry entirely."""
    calls = {"n": 0, "fast": 0}

    async def english_reply(messages, language="fr", native_language="en"):
        calls["n"] += 1
        return {"reply": "You can say 我今日好開心.", "translation": "",
                "feedback": None}

    async def fast_reply(messages, language="fr"):
        calls["fast"] += 1
        return ""

    monkeypatch.setattr("app.services.llm.chat_json", english_reply)
    monkeypatch.setattr("app.services.llm.chat_reply_fast", fast_reply)
    session_id = _init(client, level="intermediate")["session_id"]
    r = client.post(
        "/api/chat",
        data={"session_id": session_id, "language": "fr", "text": "How do I say I'm happy?"},
    )
    assert r.status_code == 200, r.text
    assert calls["n"] == 2  # greeting + turn, no retry
    assert calls["fast"] == 0  # reply-only regeneration never used


def test_stream_nudge_retry_uses_corrected_reply(client, mock_services, monkeypatch):
    """The stream path also nudge-retries a mismatched reply."""
    async def cjk_stream(messages, language="fr", native_language="en"):
        yield {"reply": "你可以話「我今日好開心」。", "translation": "",
               "feedback": None}

    async def english_nudge(messages, language="fr"):
        return "You can say 我今日好開心 — very happy today."

    monkeypatch.setattr("app.services.llm.chat_json_stream", cjk_stream)
    monkeypatch.setattr("app.services.llm.chat_reply_fast", english_nudge)
    session_id = _init(client, level="intermediate")["session_id"]
    r = client.post(
        "/api/chat/stream",
        data={"session_id": session_id, "language": "fr", "text": "How do I say I'm happy?"},
    )
    assert r.status_code == 200
    blocks = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    complete = next(b for b in blocks if b.get("reply"))
    assert complete["reply"]["text"].startswith("You can say")


def test_nudge_not_fired_by_translation_drift(client, mock_services, monkeypatch):
    """A Chinese-drifting translation NO LONGER triggers the reply-only retry
    (it cannot fix that field) — the retry only fires on reply-language
    mismatch, and the reply is never replaced."""
    calls = {"fast": 0}

    async def chinese_then_english(messages, language="fr", native_language="en"):
        return {"reply": "Great job! 早晨 means good morning.",
                "translation": "做得好！", "feedback": None}

    async def english_nudge(messages, language="fr"):
        calls["fast"] += 1
        return ""

    monkeypatch.setattr("app.services.llm.chat_json", chinese_then_english)
    monkeypatch.setattr("app.services.llm.chat_reply_fast", english_nudge)
    session_id = _init(client, level="intermediate")["session_id"]
    r = client.post(
        "/api/chat",
        data={"session_id": session_id, "language": "fr", "text": "How do I say good morning?"},
    )
    assert r.status_code == 200, r.text
    reply = r.json()["reply"]
    assert reply["text"] == "Great job! 早晨 means good morning."
    assert reply["translation"] == "做得好！"  # v10: translations flow through
    assert calls["fast"] == 0


def test_nudge_strips_typed_prefix_in_retry_check(client, mock_services, monkeypatch):
    """The [Typed]: prefix must be stripped before the script-ratio
    re-check: "[Typed]: 你好" ≈ 0.286 falls below the 0.3 CJK threshold,
    so without the strip an English retry would be WRONGLY ACCEPTED for a
    Chinese learner. With the strip it is discarded (original kept)."""
    calls = {"fast": 0}

    async def english_reply(messages, language="fr", native_language="en"):
        return {"reply": "Great to hear that!", "translation": "", "feedback": None}

    async def english_nudge(messages, language="fr"):
        calls["fast"] += 1
        return "Great job!"

    monkeypatch.setattr("app.services.llm.chat_json", english_reply)
    monkeypatch.setattr("app.services.llm.chat_reply_fast", english_nudge)
    session_id = _init(client, level="intermediate")["session_id"]
    r = client.post(
        "/api/chat",
        data={"session_id": session_id, "language": "zh", "text": "你好"},
    )
    assert r.status_code == 200, r.text
    assert calls["fast"] == 1  # the mismatch fired despite the [Typed]: prefix
    # The English retry was discarded — the original English reply stays.
    assert r.json()["reply"]["text"] == "Great to hear that!"


def test_translation_passes_through_for_intermediate(client, mock_services):
    """Intermediate/fluent replies keep their LLM translation (v10 — the
    server-side blanking was removed; beginner personas return "" by prompt
    design, so only their translations stay empty)."""
    session_id = _init(client, level="intermediate")["session_id"]
    r = client.post(
        "/api/chat",
        data={"session_id": session_id, "language": "fr", "text": "Bonjour"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["reply"]["translation"] == FAKE_PAYLOAD["translation"]


# ── v8A QA battery fixes (2026-08-02): jyutping stripping + contract examples ──

class TestJyutpingStripped:
    """Teaching replies leak parenthetical romanization ('唔該 (m4 goi1)')
    under pressure — strip it before TTS (v8B's defense-in-depth)."""

    def test_strip_jyutping_removes_parenthetical(self):
        from app.routers.chat import _strip_jyutping
        assert "m4 goi1" not in _strip_jyutping("唔該 (m4 goi1) — used for favors")
        assert "唔該" in _strip_jyutping("唔該 (m4 goi1) — used for favors")

    def test_strip_jyutping_keeps_legit_words(self):
        from app.routers.chat import _strip_jyutping
        assert "iPhone15" in _strip_jyutping("I love my iPhone15")

    def test_build_turn_strips_jyutping_from_reply(self, mock_services, monkeypatch):
        from app.routers.chat import _build_turn
        import asyncio
        payload = {"reply": "唔該 (m4 goi1) means thank you", "translation": "Thanks",
                   "feedback": None}
        turn = asyncio.run(_build_turn(payload, "yue", "", "intermediate", skip_audio=True))
        assert "m4 goi1" not in turn.text
        assert "唔該" in turn.text

    def test_strip_jyutping_multi_token_parens(self):
        """'(m4 goi1)' — multi-token parens with a 1-letter syllable — must
        be fully stripped (live-observed leak surviving the single-token form)."""
        from app.routers.chat import _strip_jyutping
        out = _strip_jyutping("唔該 (m4 goi1) — used for favors")
        assert "m4 goi1" not in out
        assert "m4" not in out
        assert "唔該" in out


def test_audio_metrics_become_delivery(client, mock_services, monkeypatch):
    """Think By Speaking audio pillars (v13.1): client-measured audio_secs/pitch_var
    become pace (words/sec) + pitch label on the spoken turn."""
    async def zh_payload(messages, language="zh", native_language="en"):
        return {
            "reply": "Fair point!",
            "translation": "Fair point!",
            "feedback": {"stance": "partially_agree", "score": 54},
        }

    monkeypatch.setattr("app.services.llm.chat_json", zh_payload)

    async def fake_transcribe(audio_bytes, language):
        return "I think that is a good point"

    monkeypatch.setattr("app.services.stt.transcribe", fake_transcribe)
    session_id = _init(client, language="en")["session_id"]
    r = client.post(
        "/api/chat",
        data={
            "session_id": session_id, "language": "en",
            "audio_secs": "4.0", "pitch_var": "12.5",
        },
        files={"audio": ("audio.webm", b"\x00\x01\x02", "audio/webm")},
    )
    assert r.status_code == 200, r.text
    delivery = r.json()["reply"]["feedback"]["delivery"]
    assert delivery["pace"] == 1.8  # 7 words / 4 s
    assert delivery["pitch"] == "monotone"  # 12.5 Hz < 25 Hz threshold

    # A varied recording (>25 Hz variance) labels 'varied'
    r2 = client.post(
        "/api/chat",
        data={
            "session_id": session_id, "language": "en",
            "audio_secs": "2.0", "pitch_var": "80.0",
        },
        files={"audio": ("audio.webm", b"\x00\x01\x02", "audio/webm")},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["reply"]["feedback"]["delivery"]["pitch"] == "varied"


def test_spoken_summary_endpoint(client, mock_services, monkeypatch):
    """v13.1 spoken recap: /chat/summary returns a spoken coach turn over
    the session history."""
    async def fake_fast(messages):
        return "You finished at 54 — your steelman of the junior-staff point was strong, but you leaned on a false dilemma early on. Next time: name your evidence first."

    monkeypatch.setattr("app.services.llm.chat_reply_fast", fake_fast)
    session_id = _init(client, language="en")["session_id"]
    r = client.post(
        "/api/chat",
        data={"session_id": session_id, "language": "en", "text": "AI will replace teachers."},
    )
    assert r.status_code == 200, r.text

    r = client.post(
        "/api/chat/summary",
        data={"session_id": session_id, "language": "en"},
    )
    assert r.status_code == 200, r.text
    reply = r.json()["reply"]
    assert "false dilemma" in reply["text"]
    assert reply["audio_base64"] == "QUJD"  # spoken (TTS synthesized)
    assert reply["feedback"] is None


def test_summary_empty_session_422(client, mock_services):
    session_id = _init(client, language="en")["session_id"]
    r = client.post("/api/chat/summary", data={"session_id": session_id, "language": "en"})
    assert r.status_code == 422
