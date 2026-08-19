"""Realtime WS tests (v11 M1, 2026-08-08) — hermetic: a fake DashScope
upstream (websockets.sync.server on a background thread) stands in for
wss://dashscope-intl.aliyuncs.com; services.grammar.check is mocked like
every other external service in this suite.
"""
import asyncio
import base64
import json
import threading
import time

import pytest
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve

from app.config import get_settings
from app.db.database import get_db
from app.realtime import languages as realtime_langs
from app.routers import realtime as realtime_router

pytestmark = pytest.mark.timeout(20)

REPLY_TEXT = "你好！今日點呀？"
TRANSCRIPT = "你好"


class FakeDashScope:
    """Scriptable fake of the DashScope realtime upstream.

    Records every client event; on a PTT commit it 'transcribes'
    next_transcript, and on response.create it plays a full tutor turn
    (response.created → one audio delta → audio_transcript.done →
    response.done). auto_done=False holds back response.done so a test can
    cancel mid-response. Not an async server — runs on its own thread.
    """

    def __init__(self):
        self.received: list[dict] = []
        self._lock = threading.Lock()
        self.next_transcript = TRANSCRIPT
        self.next_reply = REPLY_TEXT
        self.auto_done = True
        self._audio = base64.b64encode(b"\x01\x00" * 2400).decode()  # 0.1s PCM16
        self._ws = None  # set in _handler; lets tests emit server-side events

    def start(self):
        self._server = serve(self._handler, "127.0.0.1", 0)
        self.port = self._server.socket.getsockname()[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._server.shutdown()

    def _handler(self, ws):
        self._ws = ws
        try:
            for raw in ws:
                self._on_event(ws, raw)
        except ConnectionClosed:
            pass  # the bridge aborts the upstream transport at teardown

    def _on_event(self, ws, raw):
        try:
            event = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        with self._lock:
            self.received.append(event)
        etype = event.get("type")
        if etype == "input_audio_buffer.commit":
            ws.send(json.dumps({
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": self.next_transcript,
            }))
        elif etype == "response.create":
            ws.send(json.dumps({"type": "response.created"}))
            ws.send(json.dumps({
                "type": "response.audio.delta", "delta": self._audio,
            }))
            ws.send(json.dumps({
                "type": "response.audio_transcript.done",
                "transcript": self.next_reply,
            }))
            if self.auto_done:
                ws.send(json.dumps({
                    "type": "response.done", "response": {"status": "completed"},
                }))
        elif etype == "response.cancel":
            ws.send(json.dumps({
                "type": "response.done", "response": {"status": "cancelled"},
            }))

    def events(self, etype: str | None = None) -> list[dict]:
        with self._lock:
            snapshot = list(self.received)
        if etype is None:
            return snapshot
        return [e for e in snapshot if e.get("type") == etype]

    def emit_transcript(self, transcript: str = "") -> None:
        """Handsfree: the server-side VAD 'hears' the user and the upstream
        emits the ASR result unprompted (no client commit involved)."""
        self._send({
            "type": "conversation.item.input_audio_transcription.completed",
            "transcript": transcript or self.next_transcript,
        })

    def emit_response(self, transcript: str | None = None) -> None:
        """Handsfree: the upstream auto-replies after the user stops
        speaking — a full response with no client response.create."""
        self._send({"type": "response.created"})
        self._send({"type": "response.audio.delta", "delta": self._audio})
        self._send({
            "type": "response.audio_transcript.done",
            "transcript": self.next_reply if transcript is None else transcript,
        })
        if self.auto_done:
            self._send({"type": "response.done", "response": {"status": "completed"}})

    def _send(self, event: dict) -> None:
        self._ws.send(json.dumps(event))

    def wait_for(self, etype: str, timeout: float = 5.0) -> dict:
        """Poll until an upstream-received event of this type exists."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            found = self.events(etype)
            if found:
                return found[-1]
            time.sleep(0.01)
        raise AssertionError(f"upstream never received {etype!r}; got {self.events()!r}")


@pytest.fixture()
def fake_upstream(monkeypatch):
    """Point the bridge at the fake DashScope and hand it a dummy key."""
    fake = FakeDashScope().start()
    settings = get_settings()
    monkeypatch.setattr(settings, "dashscope_realtime_url", f"ws://127.0.0.1:{fake.port}")
    monkeypatch.setattr(settings, "dashscope_api_key", "test-dashscope-key")
    yield fake
    fake.stop()


@pytest.fixture(autouse=True)
def _clean_realtime_state(monkeypatch):
    """No cross-test bleed: per-IP concurrency counters + grammar mocked off."""
    realtime_router._active_by_ip.clear()

    async def no_grammar(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.grammar.check", no_grammar)
    yield
    realtime_router._active_by_ip.clear()


def ws_url(**params) -> str:
    defaults = {"lang": "yue", "level": "beginner", "mode": "ptt"}
    defaults.update(params)
    qs = "&".join(f"{k}={v}" for k, v in defaults.items() if v is not None)
    return f"/api/realtime/ws?{qs}"


def next_message(ws, kinds=("json",)):
    """Next browser message as ('json', dict) | ('bytes', bytes); skips
    binary audio unless asked for."""
    while True:
        msg = ws.receive()
        if msg.get("type") == "websocket.close":
            raise WebSocketDisconnect(msg.get("code"), msg.get("reason"))
        if msg.get("bytes") is not None:
            if "bytes" in kinds:
                return ("bytes", msg["bytes"])
            continue
        return ("json", json.loads(msg["text"]))


def collect_until(ws, pred, limit=12) -> list[dict]:
    """Read JSON events (skipping binary audio) until pred(event) or limit."""
    seen = []
    for _ in range(limit):
        kind, payload = next_message(ws)
        if kind == "bytes":
            continue
        seen.append(payload)
        if pred(payload):
            return seen
    raise AssertionError(f"no matching event; saw {seen!r}")


def ptt_turn(ws):
    """One full PTT voice turn against the fake upstream."""
    ws.send_text(json.dumps({"type": "input_audio_buffer.commit"}))
    ws.send_text(json.dumps({"type": "response.create"}))


# ── (a) session.update payload ────────────────────────────────────────

def test_session_update_ptt_cantonese(client, fake_upstream):
    with client.websocket_connect(ws_url(lang="yue", level="beginner", mode="ptt")) as ws:
        update = fake_upstream.wait_for("session.update")
    sess = update["session"]
    assert sess["voice"] == "Kiki"
    assert sess["turn_detection"] is None  # ptt → VAD off, client drives turns
    assert sess["input_audio_transcription"]["model"] == get_settings().realtime_asr_model
    assert "廣東話" in sess["instructions"]
    assert "debater" in sess["instructions"]
    assert "jyutping" not in sess["instructions"]
    assert "their native language is English" in sess["instructions"]


@pytest.mark.parametrize("level,silence", [("beginner", 1600), ("intermediate", 1100), ("fluent", 700)])
def test_session_update_handsfree_semantic_vad(client, fake_upstream, level, silence):
    with client.websocket_connect(ws_url(lang="zh", level=level, mode="handsfree")) as ws:
        update = fake_upstream.wait_for("session.update")
    sess = update["session"]
    assert sess["voice"] == "Ethan"
    assert sess["turn_detection"] == {
        "type": "semantic_vad", "threshold": 0.5, "silence_duration_ms": silence,
    }
    assert "普通话" in sess["instructions"]


@pytest.mark.parametrize("lang,voice", [
    ("yue", "Kiki"), ("zh", "Ethan"), ("zh-TW", "Cindy"), ("en", "Jennifer"),
    ("fr", "Emilien"), ("ja", "Ono Anna"),
])
def test_session_update_voice_per_language(client, fake_upstream, lang, voice):
    with client.websocket_connect(ws_url(lang=lang)) as ws:
        update = fake_upstream.wait_for("session.update")
    assert update["session"]["voice"] == voice


def test_session_update_scenario_and_native_language(client, fake_upstream):
    from app.prompts import get_scenario

    prompt = get_scenario("ai-future")["prompt"]
    with client.websocket_connect(
        ws_url(lang="fr", level="beginner", mode="ptt", scenario_id="ai-future", native="es")
    ) as ws:
        update = fake_upstream.wait_for("session.update")
    instructions = update["session"]["instructions"]
    assert "SUBJECT — debate this claim:" in instructions and prompt in instructions
    # Native language generalized (the spike hardcoded English).
    assert "their native language is Spanish" in instructions
    assert "natural French words and Spanish" in instructions


def test_continuation_hint_on_rollover_reconnect(client, fake_upstream):
    """cont=1 (session-cap rollover, v11 M2) adds a skip-the-greeting hint."""
    with client.websocket_connect(ws_url()) as ws:
        update = fake_upstream.wait_for("session.update")
    assert "continues an ongoing debate" not in update["session"]["instructions"]
    seen = len(fake_upstream.events("session.update"))
    with client.websocket_connect(ws_url(cont="1")) as ws:
        # Wait for THIS connection's session.update (wait_for would otherwise
        # return the first connection's stale one and close before upstream
        # connects).
        deadline = time.time() + 5
        while len(fake_upstream.events("session.update")) <= seen:
            assert time.time() < deadline, "second session.update never arrived"
            time.sleep(0.01)
        update = fake_upstream.events("session.update")[-1]
    assert "continues an ongoing debate" in update["session"]["instructions"]


# ── (b) ptt command forwarding ────────────────────────────────────────

def test_ptt_commands_forwarded_and_cancel_guarded(client, fake_upstream):
    with client.websocket_connect(ws_url(mode="ptt")) as ws:
        fake_upstream.wait_for("session.update")
        ws.send_text(json.dumps({"type": "response.cancel"}))  # nothing in flight
        for cmd in ("input_audio_buffer.commit", "input_audio_buffer.clear", "response.create"):
            ws.send_text(json.dumps({"type": cmd}))
        fake_upstream.wait_for("response.create")
        time.sleep(0.2)  # let any (buggy) cancel arrive
    types = [e["type"] for e in fake_upstream.events()]
    assert "input_audio_buffer.commit" in types
    assert "input_audio_buffer.clear" in types
    assert "response.create" in types
    # response.cancel with no active response must NOT be forwarded
    # (upstream errors on cancelling nothing).
    assert "response.cancel" not in types


def test_response_cancel_forwarded_while_responding(client, fake_upstream):
    fake_upstream.auto_done = False  # response stays in flight
    with client.websocket_connect(ws_url(mode="ptt")) as ws:
        fake_upstream.wait_for("session.update")
        ptt_turn(ws)
        collect_until(ws, lambda e: e.get("type") == "response.created")
        ws.send_text(json.dumps({"type": "response.cancel"}))
        fake_upstream.wait_for("response.cancel")
        events = collect_until(
            ws, lambda e: e.get("type") == "response.done"
        )
    assert len(fake_upstream.events("response.cancel")) == 1
    done = next(e for e in events if e.get("type") == "response.done")
    assert done["response"]["status"] == "cancelled"


def test_ptt_commands_not_forwarded_in_handsfree(client, fake_upstream):
    with client.websocket_connect(ws_url(mode="handsfree")) as ws:
        fake_upstream.wait_for("session.update")
        ws.send_text(json.dumps({"type": "input_audio_buffer.commit"}))
        ws.send_text(json.dumps({"type": "response.create"}))
        time.sleep(0.3)
    # handsfree = server-side VAD; manual turn commands stay client-side…
    # only session.update should have arrived.
    assert fake_upstream.events("input_audio_buffer.commit") == []
    assert fake_upstream.events("response.create") == []


def test_user_text_typed_turn(client, fake_upstream):
    with client.websocket_connect(ws_url(lang="zh", mode="ptt")) as ws:
        fake_upstream.wait_for("session.update")
        ws.send_text(json.dumps({"type": "user_text", "text": "你好"}))
        events = collect_until(ws, lambda e: e.get("type") == "response.done")
    echo = next(e for e in events if e["type"] == "proxy.user_transcript")
    assert echo["transcript"] == "你好" and echo["turn"] == 1
    assert "romanization" not in echo  # v13.1: romanization feature removed
    item = fake_upstream.wait_for("conversation.item.create")
    assert item["item"]["content"][0] == {"type": "input_text", "text": "你好"}
    assert fake_upstream.events("response.create")


# ── (c) auth ──────────────────────────────────────────────────────────

def test_bad_token_falls_back_to_guest(client, fake_upstream):
    with client.websocket_connect(ws_url(token="bogus-token")) as ws:
        update = fake_upstream.wait_for("session.update")
    assert update["session"]["voice"] == "Kiki"  # session ran as a guest


def test_registered_user_session_counts_stats(client, fake_upstream):
    r = client.post("/api/auth/register", json={"username": "wsuser", "password": "pw"})
    assert r.status_code == 201
    token = r.json()["token"]
    with client.websocket_connect(ws_url(lang="fr", token=token)) as ws:
        fake_upstream.wait_for("session.update")
        ptt_turn(ws)
        collect_until(ws, lambda e: e.get("type") == "response.done")
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    stats = me.json()["stats"]
    assert stats["total_sessions"] == 1
    assert stats["total_messages"] == 2  # user + assistant rows of the turn


# ── (d) quota disabled (v12.2 personal deploy) ─────────────────────────
# The daily-quota enforcement (4001) is deliberately dead code — guests and
# users share the upstream session cap (4000 rollover). These tests pin the
# disabled behavior so a future re-enable has to touch them deliberately.

def test_guest_with_exhausted_quota_still_connects(client, fake_upstream, monkeypatch):
    """Even with seconds_used_today reporting 9999, the connection proceeds:
    the accept-time quota check is commented out (v12.2)."""
    async def over_quota(user_id="", ip="", day=None):
        return 9999

    monkeypatch.setattr("app.db.usage_store.seconds_used_today", over_quota)
    with client.websocket_connect(ws_url()) as ws:
        update = fake_upstream.wait_for("session.update")
    assert update["session"]["modalities"] == ["text", "audio"]  # reached upstream


# ── (e) transcript guards + romanization ──────────────────────────────

def test_wrong_script_transcript_blanked_and_flagged(client, fake_upstream):
    fake_upstream.next_transcript = "หรือว่าเนเน่ เดดดี้มา"  # Thai misfire (live-observed)
    with client.websocket_connect(ws_url(lang="yue")) as ws:
        fake_upstream.wait_for("session.update")
        ptt_turn(ws)
        events = collect_until(
            ws, lambda e: e.get("type") == "conversation.item.input_audio_transcription.completed"
        )
    event = events[-1]
    assert event["transcript"] == ""
    assert event["transcript_unclear"] is True
    assert event["raw_transcript"].startswith("หรือว่า")
    assert event["turn"] == 1


def test_cjk_transcript_keeps_turn_without_romanization(client, fake_upstream):
    """v13.1: the romanization feature is gone — the turn pipeline (ASR
    echo + tutor transcript) still works for CJK transcripts."""
    with client.websocket_connect(ws_url(lang="zh")) as ws:
        fake_upstream.wait_for("session.update")
        ptt_turn(ws)
        events = collect_until(ws, lambda e: e.get("type") == "response.done")
    asr = next(
        e for e in events
        if e["type"] == "conversation.item.input_audio_transcription.completed"
    )
    assert asr["transcript"] == "你好"
    assert asr["turn"] == 1
    assert "romanization" not in asr
    tutor = next(e for e in events if e["type"] == "response.audio_transcript.done")
    assert tutor["transcript"] == REPLY_TEXT
    assert tutor["turn"] == 1
    assert "romanization" not in tutor


# ── (f) debate feedback card on turn completion ───────────────────────

def test_feedback_card_fires_on_completed_turn(client, fake_upstream, monkeypatch):
    calls = []

    async def fake_check(lang, level, native_language, user_text, tutor_text="", history_text=""):
        calls.append({"lang": lang, "level": level, "native": native_language,
                      "user": user_text, "tutor": tutor_text})
        return {"stance": "disagree", "score": 42, "score_delta": -8,
                "counter": "That claim needs evidence.",
                "evidence": "Correlation is not causation.",
                "next": "What would falsify it?"}

    monkeypatch.setattr("app.services.grammar.check", fake_check)
    with client.websocket_connect(ws_url(lang="yue", level="intermediate")) as ws:
        fake_upstream.wait_for("session.update")
        ptt_turn(ws)  # turn 1 = framing exchange — no card (v13.1)
        ptt_turn(ws)  # turn 2 = the debate starts — card fires
        events = collect_until(ws, lambda e: e.get("type") == "proxy.feedback")
    card = next(e for e in events if e["type"] == "proxy.feedback")
    assert card["turn"] == 2
    assert card["stance"] == "disagree"
    assert card["score"] == 42
    assert len(calls) == 1  # only the scored turn hit the judge
    assert calls[0] == {"lang": "yue", "level": "intermediate", "native": "en",
                        "user": "你好", "tutor": REPLY_TEXT}


def test_grammar_not_fired_for_cancelled_turn(client, fake_upstream, monkeypatch):
    calls = []

    async def fake_check(*args, **kwargs):
        calls.append(args)
        return {"stance": "partially_agree", "score": 50, "score_delta": 0,
                "counter": "", "evidence": "", "next": ""}

    monkeypatch.setattr("app.services.grammar.check", fake_check)
    fake_upstream.auto_done = False
    with client.websocket_connect(ws_url(mode="ptt")) as ws:
        fake_upstream.wait_for("session.update")
        ptt_turn(ws)
        collect_until(ws, lambda e: e.get("type") == "response.created")
        ws.send_text(json.dumps({"type": "response.cancel"}))
        collect_until(ws, lambda e: e.get("type") == "response.done")
        time.sleep(0.3)  # a buggy feedback task would have fired by now
    # A cancelled response.done never completes the turn → no feedback task.
    assert calls == []


# ── (g) session-cap rollover ──────────────────────────────────────────

def test_rollover_close_4000_when_audio_cap_hit(client, fake_upstream, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "realtime_max_audio_seconds", 1)  # 32 000 B in
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(ws_url()) as ws:
            fake_upstream.wait_for("session.update")
            events = []
            ws.send_bytes(b"\x00" * 20000)  # 0.625 s
            ws.send_bytes(b"\x00" * 20000)  # 1.25 s → over the 1 s cap
            while True:
                kind, payload = next_message(ws, kinds=("json", "bytes"))
                if kind == "json":
                    events.append(payload)
    assert excinfo.value.code == 4000
    assert any(e.get("type") == "proxy.session_cap" for e in events)


def test_trial_below_cap_still_closes_4000_session_cap(client, fake_upstream, monkeypatch):
    """The trial setting no longer affects the close code — the session cap
    (4000 rollover) is the only limiter (v12.2)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "realtime_guest_trial_seconds", 1)
    monkeypatch.setattr(settings, "realtime_max_audio_seconds", 1)  # session cap 1 s

    async def no_prior_usage(user_id="", ip="", day=None):
        return 0  # isolate from other tests' usage flushes

    monkeypatch.setattr("app.db.usage_store.seconds_used_today", no_prior_usage)
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(ws_url()) as ws:
            fake_upstream.wait_for("session.update")
            events = []
            ws.send_bytes(b"\x00" * 64000)  # 2 s of audio at once
            while True:
                kind, payload = next_message(ws, kinds=("json", "bytes"))
                if kind == "json":
                    events.append(payload)
    assert excinfo.value.code == 4000
    assert any(e.get("type") == "proxy.session_cap" for e in events)
    assert not any(e.get("type") == "proxy.quota_exhausted" for e in events)


# ── (h) unsupported language ──────────────────────────────────────────

def test_unsupported_language_closed_1008(client, fake_upstream):
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(ws_url(lang="el")) as ws:
            event = next_message(ws)[1]
            assert event["type"] == "error"
            assert event["error"]["code"] == "unsupported_language"
            assert "Greek" in event["error"]["message"]
            next_message(ws)
    assert excinfo.value.code == 1008
    assert fake_upstream.events("session.update") == []


def test_bad_level_and_mode_closed_1008(client, fake_upstream):
    for params in ({"level": "A1"}, {"mode": "vox"}):
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect(ws_url(**params)) as ws:
                assert next_message(ws)[1]["type"] == "error"
                next_message(ws)
        assert excinfo.value.code == 1008


# ── (i) /api/languages realtime flag ──────────────────────────────────

def test_languages_carry_realtime_flag(client):
    langs = {l["code"]: l for l in client.get("/api/languages").json()}
    assert langs["yue"]["realtime"] is True
    assert langs["zh-TW"]["realtime"] is True
    assert langs["fil"]["realtime"] is True   # via Tagalog
    assert langs["el"]["realtime"] is False
    assert langs["ta"]["realtime"] is False
    assert set(realtime_langs.REALTIME_LANGS) == {
        code for code, l in langs.items() if l["realtime"]
    }


# ── persistence: realtime turns land in the messages table ────────────

def test_completed_turn_persisted_to_messages(client, fake_upstream):
    r = client.post("/api/auth/register", json={"username": "hist", "password": "pw"})
    token = r.json()["token"]

    async def query():
        db = get_db()
        async with db.execute(
            "SELECT m.role, m.text, m.pronunciation FROM messages m "
            "JOIN sessions s ON s.id = m.session_id "
            "WHERE s.user_id = (SELECT user_id FROM tokens WHERE token = ?) "
            "ORDER BY m.seq",
            (token,),
        ) as cur:
            return await cur.fetchall()

    with client.websocket_connect(ws_url(lang="zh", token=token)) as ws:
        fake_upstream.wait_for("session.update")
        ptt_turn(ws)
        collect_until(ws, lambda e: e.get("type") == "response.done")
        # Turns are flushed eagerly at completion — poll while the WS is
        # still open (closing first would let the TestClient's
        # cancel-on-close race the flush).
        deadline = time.time() + 5
        rows = []
        while time.time() < deadline:
            rows = asyncio.run(query())
            if len(rows) >= 2:
                break
            time.sleep(0.05)
    assert [(r["role"], r["text"]) for r in rows] == [
        ("user", "你好"), ("assistant", REPLY_TEXT),
    ]
    assert "nǐ" in rows[0]["pronunciation"]


# ── usage_store roundtrip (DB-level) ──────────────────────────────────

def test_usage_audio_roundtrip(client):
    from app.db import usage_store

    async def scenario():
        await usage_store.add_seconds("", "10.0.0.9", 7)
        await usage_store.add_seconds("", "10.0.0.9", 5)
        guest = await usage_store.seconds_used_today("", "10.0.0.9")
        await usage_store.add_seconds("user-1", "", 30)
        registered = await usage_store.seconds_used_today("user-1", "")
        other_ip = await usage_store.seconds_used_today("", "10.0.0.10")
        return guest, registered, other_ip

    guest, registered, other_ip = asyncio.run(scenario())
    assert guest == 12
    assert registered == 30
    assert other_ip == 0


# ── (h) learner profile passthrough (v13 — the personalization moat) ──

def test_profile_injected_into_realtime_instructions(client, fake_upstream):
    """The WS profile param reaches the coach's session.update instructions."""
    import urllib.parse

    profile = urllib.parse.quote('{"interests": ["tech"], "style": "socratic"}')
    with client.websocket_connect(ws_url(lang="en", level="intermediate", profile=profile)) as ws:
        update = fake_upstream.wait_for("session.update")
    instructions = update["session"]["instructions"]
    assert "LEARNER PROFILE" in instructions
    assert "tech" in instructions
    assert "socratic" in instructions


def test_malformed_profile_ignored(client, fake_upstream):
    """Bad profile JSON must not break the connection (server drops it)."""
    with client.websocket_connect(ws_url(lang="en", profile="not-json")) as ws:
        update = fake_upstream.wait_for("session.update")
    assert "LEARNER PROFILE" not in update["session"]["instructions"]


# ── (i) moderator handover (v13, user-directed 2026-08-19) ──────────

def test_moderator_voice_handover_after_greeting(client, fake_upstream):
    """The host voice (Jennifer) opens the session; after turn 1 the bridge
    sends a mid-session session.update switching to the coach voice
    (Ethan) — the moderator speaks the intro, the coach debates."""
    with client.websocket_connect(ws_url(lang="en", level="intermediate", voice="Ethan")) as ws:
        fake_upstream.wait_for("session.update")
        first = fake_upstream.events("session.update")[-1]
        ptt_turn(ws)
        deadline = time.time() + 5
        while len(fake_upstream.events("session.update")) < 2:
            assert time.time() < deadline, "handover session.update never arrived"
            time.sleep(0.01)
        handover = fake_upstream.events("session.update")[-1]
    assert first["session"]["voice"] == "Jennifer"   # the host opens the debate
    assert handover["session"]["voice"] == "Ethan"   # the coach takes over


# ── (j) delivery metrics (v13.1): turn_metrics -> pace + pitch ──────

def test_turn_metrics_become_delivery_on_card(client, fake_upstream, monkeypatch):
    """The client's turn_metrics frame (pitch variance + duration) becomes
    pace + pitch on the debate card for that turn."""
    async def fake_check(lang, level, native_language, user_text, tutor_text="", history_text=""):
        return {"stance": "partially_agree", "score": 50, "score_delta": 0,
                "counter": "", "evidence": "", "next": "",
                "fallacies": [], "structure": ""}

    monkeypatch.setattr("app.services.grammar.check", fake_check)
    with client.websocket_connect(ws_url(lang="en", level="intermediate")) as ws:
        fake_upstream.wait_for("session.update")
        ws.send_text(json.dumps({"type": "turn_metrics", "pitch_var": 80.0, "secs": 3.0}))
        ptt_turn(ws)  # framing turn — no card
        ws.send_text(json.dumps({"type": "turn_metrics", "pitch_var": 80.0, "secs": 3.0}))
        ptt_turn(ws)  # scored turn
        events = collect_until(ws, lambda e: e.get("type") == "proxy.feedback")
    card = next(e for e in events if e["type"] == "proxy.feedback")
    assert card["delivery"]["pitch"] == "varied"   # 80 Hz variance > 25
    # pace: the ptt_turn transcript is "你好" (1 word) over 3 s → 0.3 w/s
    assert card["delivery"]["pace"] == 0.3


def test_no_metrics_no_delivery(client, fake_upstream, monkeypatch):
    async def fake_check(lang, level, native_language, user_text, tutor_text="", history_text=""):
        return {"stance": "partially_agree", "score": 50, "score_delta": 0,
                "counter": "", "evidence": "", "next": "",
                "fallacies": [], "structure": ""}

    monkeypatch.setattr("app.services.grammar.check", fake_check)
    with client.websocket_connect(ws_url(lang="en", level="intermediate")) as ws:
        fake_upstream.wait_for("session.update")
        ptt_turn(ws)  # framing — no card
        ptt_turn(ws)  # scored turn
        events = collect_until(ws, lambda e: e.get("type") == "proxy.feedback")
    card = next(e for e in events if e["type"] == "proxy.feedback")
    assert "delivery" not in card
    assert card["filler_count"] == 0


def test_non_realtime_voice_falls_back_to_preset(client, fake_upstream):
    """An edge/ElevenLabs voice id must never reach the qwen engine — the
    bridge falls back to the language preset (v13.1 regression guard)."""
    with client.websocket_connect(ws_url(lang="en", voice="en-GB-RyanNeural")) as ws:
        update = fake_upstream.wait_for("session.update")
    assert update["session"]["voice"] == "Jennifer"  # en preset, not the edge id


# ── (k) moderator interjection (v13.1, default ON) ───────────────────

def test_moderator_interjects_before_coach_on_even_turns(client, fake_upstream, monkeypatch):
    """Turn 2+ (even): the host voice speaks a neutral line first — the
    bridge sends session.update(host voice) + a response.create, then
    switches back to the coach voice for the real reply."""
    async def fake_fast(messages):
        return "A fair challenge — the coach owes you a steelman there."

    monkeypatch.setattr("app.services.llm.chat_reply_fast", fake_fast)
    with client.websocket_connect(ws_url(lang="en", level="intermediate", voice="Ethan")) as ws:
        fake_upstream.wait_for("session.update")
        ptt_turn(ws)  # framing turn (1)
        ptt_turn(ws)  # turn 2 — moderator interjection + coach reply
        collect_until(ws, lambda e: e.get("type") == "response.done", limit=24)
    updates = fake_upstream.events("session.update")
    voices = [u["session"].get("voice") for u in updates]
    # Jennifer (host) interjection, then back to Ethan (coach)
    assert "Jennifer" in voices
    creates = fake_upstream.events("response.create")
    assert len(creates) >= 2  # moderator line + coach reply


def test_moderator_skips_when_disabled(client, fake_upstream, monkeypatch):
    async def fake_fast(messages):
        return "A fair challenge."

    monkeypatch.setattr("app.services.llm.chat_reply_fast", fake_fast)
    import urllib.parse
    profile = urllib.parse.quote('{"moderator": false}')
    with client.websocket_connect(ws_url(lang="en", level="intermediate", voice="Ethan", profile=profile)) as ws:
        fake_upstream.wait_for("session.update")
        ptt_turn(ws)
        ptt_turn(ws)
        collect_until(ws, lambda e: e.get("type") == "response.done", limit=24)
    voices = [u["session"].get("voice") for u in fake_upstream.events("session.update")]
    assert "Jennifer" not in voices  # moderator off → no host voice switch


def test_spoken_turn_moderator_interjects_via_proxy_event(client, fake_upstream, monkeypatch):
    """PTT spoken turns on even turns get a proxy.moderator event + the host
    voice switch; the held response.create is released after the host line."""
    async def fake_fast(messages):
        return "The coach owes you a steelman there."

    monkeypatch.setattr("app.services.llm.chat_reply_fast", fake_fast)
    with client.websocket_connect(ws_url(lang="en", level="intermediate", voice="Ethan")) as ws:
        fake_upstream.wait_for("session.update")
        ptt_turn(ws)  # framing turn
        ptt_turn(ws)  # turn 2 — moderator + coach
        events = collect_until(ws, lambda e: e.get("type") == "proxy.moderator", limit=24)
        # The coach's held response.create is released right after the host
        # line — wait for it, then the coach's reply, so teardown can't cut
        # the turn short (a create released after the client closes is lost).
        deadline = time.time() + 5
        while len(fake_upstream.events("response.create")) < 3:
            assert time.time() < deadline, "released coach response.create never arrived"
            time.sleep(0.01)
        collect_until(ws, lambda e: e.get("type") == "response.done", limit=24)
    mod = next(e for e in events if e.get("type") == "proxy.moderator")
    assert "steelman" in mod["text"]
    voices = [u["session"].get("voice") for u in fake_upstream.events("session.update")]
    assert "Jennifer" in voices  # the host spoke
    creates = fake_upstream.events("response.create")
    assert len(creates) >= 3  # moderator line + released coach response (2 turns)


def test_handsfree_moderator_speaks_after_coach_on_even_turns(client, fake_upstream, monkeypatch):
    """Handsfree turns are upstream-driven (semantic_vad): there is no
    client response.create to hold, so the host speaks AFTER the coach's
    reply on even turns — proxy.moderator + a Jennifer response.create,
    then the voice returns to Ethan (the moderator response is not a
    tracked turn)."""
    async def fake_fast(messages):
        return "A fair challenge — the coach owes you a steelman there."

    monkeypatch.setattr("app.services.llm.chat_reply_fast", fake_fast)
    with client.websocket_connect(
        ws_url(lang="en", level="intermediate", mode="handsfree", voice="Ethan")
    ) as ws:
        fake_upstream.wait_for("session.update")
        # Turn 1 (framing): the user speaks, the upstream auto-replies.
        fake_upstream.emit_transcript("你好")
        fake_upstream.emit_response()
        collect_until(ws, lambda e: e.get("type") == "response.done")
        # Turn 2 (debate start, even): the coach replies first, THEN the host.
        fake_upstream.emit_transcript("你好")
        fake_upstream.emit_response()
        events = collect_until(ws, lambda e: e.get("type") == "proxy.moderator", limit=24)
        # The host line landed at the coach's response.done: the forwarded
        # response.done and then the host's own response.created come right
        # after it (her audio_transcript events are suppressed, so no coach
        # bubble ever carries her line).
        done = next_message(ws)
        created = next_message(ws)
        # Her response is still in flight and its response.done is
        # proxy-side (never forwarded to the browser) — wait for the
        # switch-back so teardown can't cut the host's turn short.
        deadline = time.time() + 5
        while len(fake_upstream.events("session.update")) < 5:
            assert time.time() < deadline, "moderator switch-back never arrived"
            time.sleep(0.01)
    mod = next(e for e in events if e.get("type") == "proxy.moderator")
    assert "steelman" in mod["text"]
    assert mod["turn"] == 2
    # The host line came after the coach's reply text, right before the
    # coach's own response.done — never before the coach spoke.
    assert done[1]["type"] == "response.done"
    assert created[1]["type"] == "response.created"
    coach_text = [e for e in events if e.get("type") == "response.audio_transcript.done"]
    assert len(coach_text) == 1 and coach_text[0]["transcript"] == REPLY_TEXT
    assert not any("steelman" in (e.get("transcript") or "")
                   for e in events if e.get("type", "").startswith("response.audio_transcript"))
    voices = [u["session"].get("voice") for u in fake_upstream.events("session.update")]
    # Jennifer opens the session, hands to Ethan after turn 1, returns for
    # the turn-2 interjection, and hands back to Ethan once the host spoke.
    # (The turn-1 handover fires twice — once from the ASR event, once from
    # the response.done — pre-existing behavior shared with the PTT path.)
    assert voices == ["Jennifer", "Ethan", "Ethan", "Jennifer", "Ethan"]
    creates = fake_upstream.events("response.create")
    assert len(creates) == 1  # the host line is the only handsfree response.create
    assert "steelman" in creates[0].get("instructions", "")


def test_handsfree_moderator_skips_when_disabled(client, fake_upstream, monkeypatch):
    """moderator:false — the host never speaks in handsfree either: no
    Jennifer in any session.update, no proxy.moderator, no extra
    response.create."""
    import urllib.parse

    async def fake_fast(messages):
        return "A fair challenge."

    monkeypatch.setattr("app.services.llm.chat_reply_fast", fake_fast)
    profile = urllib.parse.quote('{"moderator": false}')
    with client.websocket_connect(
        ws_url(lang="en", level="intermediate", mode="handsfree", voice="Ethan", profile=profile)
    ) as ws:
        fake_upstream.wait_for("session.update")
        fake_upstream.emit_transcript("你好")
        fake_upstream.emit_response()
        collect_until(ws, lambda e: e.get("type") == "response.done")  # turn 1
        fake_upstream.emit_transcript("你好")
        fake_upstream.emit_response()
        events = collect_until(ws, lambda e: e.get("type") == "response.done")  # turn 2
        time.sleep(0.2)  # a buggy moderator would have spoken by now
    assert not any(e.get("type") == "proxy.moderator" for e in events)
    voices = [u["session"].get("voice") for u in fake_upstream.events("session.update")]
    assert "Jennifer" not in voices
    assert fake_upstream.events("response.create") == []  # no moderator line
