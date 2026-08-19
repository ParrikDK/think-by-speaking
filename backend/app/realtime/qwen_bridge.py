"""Browser ⇄ proxy ⇄ DashScope qwen3.5-omni realtime bridge.

v11 M1 (2026-08-08). Port of the live-tested spike
(spike/qwen-realtime/server.py) onto app infrastructure: settings from
app.config, loguru logging, services.romanize imported normally (no
sys.path hacks), turn state in realtime.turns.TurnTracker, debate
feedback cards via services.grammar, and usage_audio quota metering.

Protocol reference (verified 2026-08-06):
  - https://docs.qwencloud.com/developer-guides/speech/realtime-multimodal-speech
  - https://docs.qwencloud.com/api-reference/real-time-multimodal/client-events
  - https://docs.qwencloud.com/api-reference/real-time-multimodal/server-events

Session caps / rollover: upstream limits a session to 600s of audio. When
the metered audio (input + output) crosses realtime_max_audio_seconds the
browser WS is closed with code 4000 — the client silently reconnects
(frontend, M2). When the daily quota runs out first, the close code is
4001 (client renders the trial/upsell card).
"""
import asyncio
import base64
import json
import re
import time

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from ..config import get_settings
from ..db import usage_store
from ..db.session_store import SessionData, session_store
from ..prompts.realtime_personas import (
    REALTIME_MODERATOR_VOICES,
    build_instructions,
    silence_ms_for,
    voice_for,
)
from ..services import delivery, grammar, llm
from .turns import TurnTracker

# Plus only (spike, 2026-08-07): user testing confirmed flash is the weak
# tier — it read jyutping parentheticals aloud despite the persona and
# stumbled words; plus does neither.
DEFAULT_MODEL = "qwen3.5-omni-plus-realtime"

# Input PCM16 16 kHz = 32000 B/s; output PCM16 24 kHz = 48000 B/s.
_INPUT_BYTES_PER_SEC = 32000
_OUTPUT_BYTES_PER_SEC = 48000

# The fixed ASR display model (qwen3-asr-flash-realtime, not configurable
# per the docs) occasionally turns Cantonese speech into a completely
# foreign script — observed live 2026-08-07: spoken Cantonese → Thai. The
# omni model still understood the audio; only the bubble text is garbage.
# No language-hint parameter exists, so wrong-script transcripts are
# detected deterministically and flagged for the UI.
_WRONG_SCRIPT_RE = re.compile(
    "[ᄀ-ᅟ가-힣぀-ヿЀ-ӿ؀-ۿ֐-׿ऀ-ॿঀ-৾ஂ-௿แ-๟]"
)

# Same misfire, Latin-script flavor: 唔使 → "Hmm, ça va." (French,
# 2026-08-08). Accented Latin letters essentially never appear in real
# English or Chinese transcripts, so they mark a misdetected language too.
_DIACRITIC_RE = re.compile("[À-ɏ]")

# The guard only makes sense where transcripts should be CJK or plain
# ASCII — accented Latin is legitimate text for e.g. French sessions.
_WRONG_SCRIPT_LANGS = ("yue", "zh", "zh-TW")


def _wrong_script(text: str) -> bool:
    """True when a yue/zh-session transcript looks like the wrong language:
    foreign-script chars or accented Latin, and no CJK at all (any CJK
    present = plausible transcript, keep it)."""
    if any("一" <= c <= "鿿" for c in text):
        return False
    return bool(_WRONG_SCRIPT_RE.search(text) or _DIACRITIC_RE.search(text))


def build_session_update(
    lang: str,
    level: str,
    mode: str = "handsfree",
    native_language: str = "en",
    scenario_prompt: str | None = None,
    continuation: bool = False,
    asr_model: str = "gummy-realtime-v1",
    profile: dict | None = None,
    voice: str | None = None,
) -> dict:
    """session.update payload. Field names per the qwen3.5-omni realtime docs.

    ptt: turn_detection null disables VAD — the client drives turns with
    input_audio_buffer.commit + response.create. handsfree: semantic_vad
    (recommended for the qwen3.5-omni-realtime series) with level-based
    silence patience. `voice` overrides the per-language preset when the
    learner picked a voice in setup (v13)."""
    return {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "voice": voice or voice_for(lang),
            "input_audio_format": "pcm",
            "output_audio_format": "pcm",
            # Enables user-speech transcription (separate display ASR
            # model; the stronger tier via settings.realtime_asr_model).
            "input_audio_transcription": {"model": asr_model},
            "turn_detection": (
                None if mode == "ptt" else {
                    "type": "semantic_vad",
                    "threshold": 0.5,
                    "silence_duration_ms": silence_ms_for(level),
                }
            ),
            "instructions": build_instructions(
                lang, level, native_language, scenario_prompt, continuation, profile
            ),
        },
    }


async def send_error(browser: WebSocket, message: str, code: str = "proxy"):
    """Send an OpenAI-realtime-shaped error event the page can render."""
    try:
        await browser.send_text(json.dumps({
            "type": "error",
            "error": {"type": "realtime_proxy_error", "code": code, "message": message},
        }))
    except Exception:
        pass


class _AudioMeter:
    """Per-connection audio accounting: quota usage + session-cap rollover.

    Seconds are derived from byte counts (PCM16: in 16 kHz, out 24 kHz).
    Whole seconds are flushed to usage_audio as they accumulate and at
    teardown; `exceeded` tells the pumps to close the connection.
    """

    # Flush cadence — one tiny UPDATE per 5s of audio.
    _FLUSH_EVERY = 5.0

    def __init__(self, user_id: str, ip: str, limit_seconds: float, close_code: int):
        self.user_id = user_id
        self.ip = ip
        self.limit_seconds = limit_seconds
        self.close_code = close_code
        self.in_seconds = 0.0
        self.out_seconds = 0.0
        self._unflushed = 0.0

    @property
    def total_seconds(self) -> float:
        return self.in_seconds + self.out_seconds

    @property
    def exceeded(self) -> bool:
        return self.total_seconds >= self.limit_seconds

    def add_input(self, nbytes: int) -> None:
        secs = nbytes / _INPUT_BYTES_PER_SEC
        self.in_seconds += secs
        self._unflushed += secs

    def add_output(self, nbytes: int) -> None:
        secs = nbytes / _OUTPUT_BYTES_PER_SEC
        self.out_seconds += secs
        self._unflushed += secs

    async def maybe_flush(self) -> None:
        if self._unflushed >= self._FLUSH_EVERY:
            await self.flush()

    async def flush(self) -> None:
        whole = int(self._unflushed)
        if whole <= 0:
            return
        try:
            await usage_store.add_seconds(self.user_id, self.ip, whole)
            self._unflushed -= whole
        except Exception as exc:
            logger.warning("usage_audio flush failed: {}", exc)


async def run_bridge(
    browser: WebSocket,
    *,
    lang: str,
    level: str,
    mode: str,
    native_language: str,
    scenario_prompt: str | None,
    session: SessionData,
    user_id: str,
    client_ip: str,
    quota_remaining_seconds: float,
    continuation: bool = False,
    profile: dict | None = None,
    voice: str | None = None,
) -> None:
    """Run one realtime session until either side drops. Never raises.
    `continuation` (v11 M2) tells the persona this is a session-cap
    rollover reconnect — no fresh greeting."""
    settings = get_settings()
    tracker = TurnTracker(session)
    # v13 moderator (default ON): the host speaks the greeting, then the
    # coach takes over (mid-session voice switch after turn 1). The
    # profile can switch the moderator off entirely (moderator: false).
    moderator_on = (session.profile or {}).get("moderator", True) is not False
    moderator_voice = REALTIME_MODERATOR_VOICES.get(lang)
    start_voice = (
        moderator_voice
        if (moderator_on and moderator_voice and moderator_voice != voice)
        else voice
    )
    session_cap = float(settings.realtime_max_audio_seconds)
    meter = _AudioMeter(
        user_id,
        client_ip,
        # Daily quota enforcement disabled (2026-08-17, personal deploy —
        # no accounts, no limits): the meter only enforces the upstream
        # session cap (540 s), closing 4000 so the client silently
        # reconnects. The 4001 quota/upsell close is dead code.
        # limit_seconds=min(quota_remaining_seconds, session_cap),
        # close_code=4001 if quota_remaining_seconds < session_cap else 4000,
        limit_seconds=session_cap,
        close_code=4000,
    )

    # --- connect upstream ----------------------------------------------
    upstream = None
    try:
        upstream = await websockets.connect(
            f"{settings.dashscope_realtime_url}?model={DEFAULT_MODEL}",
            additional_headers={
                "Authorization": f"Bearer {settings.dashscope_api_key}",
            },
            max_size=None,        # audio frames can be large
            open_timeout=15,
            ping_interval=20,     # keepalive through idle stretches
        )
    except Exception as exc:
        await send_error(browser, f"failed to connect to DashScope: {exc!r}")
        await browser.close(code=1011)
        return

    await upstream.send(json.dumps(build_session_update(
        lang, level, mode, native_language, scenario_prompt, continuation,
        asr_model=settings.realtime_asr_model,
        profile=profile,
        voice=start_voice,
    )))
    logger.info(
        "REALTIME SESSION start id={} lang={} level={} mode={} native={} user={}",
        session.id[:8], lang, level, mode, native_language, user_id or "guest",
    )

    # True while the model has a response in flight (response.created ..
    # response.done). Needed because response.cancel errors when no
    # response is active.
    state = {"responding": False, "first_audio_at": None, "audio_deltas": 0,
             "audio_bytes": 0, "bg": set(), "moderator_pending": False}
    # v13.1: client-measured delivery metrics for the NEXT turn (sent as a
    # turn_metrics frame right before input_audio_buffer.commit).
    pending_metrics: dict = {}

    async def close_for_meter():
        """Session-cap close: explanatory event, then the code the client
        keys its behavior on (4000 reconnect; 4001 upsell is dead since the
        daily quota was disabled 2026-08-17)."""
        kind = "quota_exhausted" if meter.close_code == 4001 else "session_cap"
        logger.info(
            "REALTIME {} id={} after {:.1f}s audio",
            kind, session.id[:8], meter.total_seconds,
        )
        try:
            await browser.send_text(json.dumps({
                "type": f"proxy.{kind}",
                "audio_seconds": round(meter.total_seconds, 1),
            }))
        except Exception:
            pass
        await browser.close(code=meter.close_code, reason=kind)

    async def feedback_card(turn: int, user_text: str, tutor_text: str):
        """Fire the DeepSeek judge; on success send proxy.feedback.
        Any failure is logged and skipped — never breaks the session."""
        history_text = "\n".join(
            f"{m['role']}: {m['text']}"
            for m in session.messages[-6:]
            if m.get("text")
        )
        result = await grammar.check(
            lang, level, native_language, user_text, tutor_text, history_text
        )
        if result is None:
            return
        # v13.1 delivery pillars: realtime turns are always spoken; attach
        # the client-measured pitch variance + pace when provided.
        result["filler_count"] = delivery.count_fillers(user_text)
        if pending_metrics:
            delivery.attach_metrics(
                result, user_text,
                pending_metrics.get("secs"), pending_metrics.get("pitch_var"),
            )
            pending_metrics.clear()
        try:
            await browser.send_text(json.dumps({
                "type": "proxy.feedback",
                "turn": turn,
                **result,
            }))
            logger.info(
                "REALTIME FEEDBACK turn={} stance={} score={}",
                turn, result["stance"], result["score"],
            )
        except Exception:
            pass  # browser already gone — the card is best-effort

    def maybe_fire_feedback(turn: int):
        """Fire the judge once both halves of a turn exist: the user
        transcript and a non-cancelled response.done for that turn.
        Turn 1 is the framing exchange (moderator definition + the
        learner's position) — no points until the debate starts."""
        if turn <= 1:
            return
        rec = tracker.records.get(turn)
        if not rec or rec.grammar_sent or not rec.response_done or not rec.user:
            return
        rec.grammar_sent = True
        task = asyncio.create_task(feedback_card(turn, rec.user, rec.tutor))
        state["bg"].add(task)
        task.add_done_callback(state["bg"].discard)

    async def _moderator_line_realtime(claim: str) -> str:
        """One short neutral host line before the coach's reply (v13.1).
        Best-effort: '' on failure — the debate proceeds without it."""
        try:
            line = await llm.chat_reply_fast([
                {"role": "system", "content": (
                    "You are the neutral debate moderator. One short spoken "
                    "line (max 2 sentences, same language as the claim): a "
                    "clarifying question, a fairness call, or a score hint. "
                    "Never take sides. Reply with ONLY the line."
                )},
                {"role": "user", "content": f'The learner claimed: "{claim}"'},
            ])
            return (line or "").strip()
        except Exception:
            return ""

    async def after_turn_event(turn: int):
        """Persist + feedback-check a turn as soon as it completes. On the
        FIRST completed turn (the moderator's greeting), switch the session
        voice from the host to the coach (v13, user-directed 2026-08-19)."""
        if turn <= 0:
            return
        if turn == 1 and moderator_on and moderator_voice and voice and moderator_voice != voice:
            try:
                await upstream.send(json.dumps({
                    "type": "session.update",
                    "session": {"voice": voice},
                }))
                logger.info(
                    "REALTIME moderator handover: host {} -> coach {}",
                    moderator_voice, voice,
                )
            except Exception as exc:
                logger.warning("voice switch after greeting failed: {}", exc)
        await tracker.persist_turn(turn)
        maybe_fire_feedback(turn)

    async def browser_to_upstream():
        """Mic PCM16 chunks -> input_audio_buffer.append; text cmds passthrough."""
        while True:
            msg = await browser.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data:
                meter.add_input(len(data))
                if meter.exceeded:
                    await close_for_meter()
                    return
                await meter.maybe_flush()
                b64 = base64.b64encode(data).decode("ascii")
                await upstream.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": b64,
                }))
            else:
                text = msg.get("text")
                if not text:
                    continue
                try:
                    cmd = json.loads(text)
                except json.JSONDecodeError:
                    continue
                ctype = cmd.get("type")
                # v13.1: delivery metrics for the next turn — proxy-only
                # (never forwarded upstream).
                if ctype == "turn_metrics":
                    pending_metrics.update({
                        "pitch_var": float(cmd.get("pitch_var") or 0),
                        "secs": float(cmd.get("secs") or 0),
                    })
                    continue
                # Guard against cancelling nothing: upstream errors on that.
                if ctype == "response.cancel" and state["responding"]:
                    logger.debug("REALTIME BROWSER->UP response.cancel (manual interrupt)")
                    # Clear the flag so a user_text right behind it doesn't
                    # send a duplicate cancel (which upstream would reject).
                    state["responding"] = False
                    await upstream.send(json.dumps({"type": "response.cancel"}))
                elif ctype in ("input_audio_buffer.commit", "input_audio_buffer.clear",
                               "response.create"):
                    # Push-to-talk: the client drives turns manually. Only
                    # meaningful when the session runs with VAD off (ptt mode).
                    if mode == "ptt":
                        logger.debug("REALTIME BROWSER->UP {}", ctype)
                        await upstream.send(json.dumps({"type": ctype}))
                elif ctype == "user_text":
                    # Typed input: same turn pipeline as speech, minus the mic.
                    text = (cmd.get("text") or "").strip()
                    if not text:
                        continue
                    turn = tracker.note_user_transcript(text)
                    logger.info("REALTIME user_text turn={}: \"{}\"", turn, text[:80])
                    # The page renders the user bubble ONLY from this echo.
                    await browser.send_text(json.dumps({
                        "type": "proxy.user_transcript",
                        "transcript": text,
                        "turn": turn,
                    }))
                    await after_turn_event(turn)
                    if state["responding"]:
                        logger.debug("REALTIME user_text while responding -> response.cancel (typed barge-in)")
                        state["responding"] = False
                        await upstream.send(json.dumps({"type": "response.cancel"}))
                    # v13.1 moderator (default ON): on even debate turns the
                    # host speaks a neutral interjection BEFORE the coach —
                    # a second voice via the proven mid-session switch. The
                    # moderator response is not a tracked turn.
                    if (
                        not state["moderator_pending"]
                        and turn >= 2 and turn % 2 == 0
                        and moderator_voice and moderator_voice != voice
                        and (session.profile or {}).get("moderator", True) is not False
                    ):
                        line = await _moderator_line_realtime(text)
                        if line:
                            state["moderator_pending"] = True
                            await upstream.send(json.dumps({
                                "type": "session.update",
                                "session": {"voice": moderator_voice},
                            }))
                            await upstream.send(json.dumps({
                                "type": "response.create",
                                "instructions": (
                                    "Say exactly this one line and nothing "
                                    f"else, in the learner's language: {line}"
                                ),
                            }))
                    await upstream.send(json.dumps({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": text}],
                        },
                    }))
                    await upstream.send(json.dumps({"type": "response.create"}))

    async def upstream_to_browser():
        """Audio deltas -> binary frames; every other event -> JSON text frame."""
        async for raw in upstream:
            try:
                event = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            etype = event.get("type", "")

            if etype == "response.audio.delta":
                now = time.monotonic()
                if state["first_audio_at"] is None:
                    state["first_audio_at"] = now
                    state["audio_deltas"] = 0
                    state["audio_bytes"] = 0
                pcm = base64.b64decode(event.get("delta") or b"")
                state["audio_deltas"] += 1
                state["audio_bytes"] += len(pcm)
                meter.add_output(len(pcm))
                if meter.exceeded:
                    await close_for_meter()
                    return
                await meter.maybe_flush()
                if pcm:
                    await browser.send_bytes(pcm)
                continue

            if etype == "response.created":
                state["responding"] = True
                state["first_audio_at"] = None
                state["audio_deltas"] = 0
                state["audio_bytes"] = 0
            elif etype == "response.done":
                state["responding"] = False
                status = (event.get("response") or {}).get("status", "?")
                logger.info(
                    "REALTIME response.done status={} audio: {} deltas / {}B",
                    status, state["audio_deltas"], state["audio_bytes"],
                )
                if state["moderator_pending"]:
                    # The moderator's interjection finished — hand the floor
                    # to the coach (its response was queued right after).
                    state["moderator_pending"] = False
                    if voice:
                        await upstream.send(json.dumps({
                            "type": "session.update",
                            "session": {"voice": voice},
                        }))
                    continue
                tracker.note_response_done(cancelled=(status == "cancelled"))
                await after_turn_event(tracker.turn)
            elif etype == "input_audio_buffer.speech_started" and state["responding"]:
                # Barge-in: cancel the in-flight response when the user talks
                # over it. The page flushes its playback queue on the same event.
                logger.debug("REALTIME speech_started -> response.cancel (barge-in)")
                state["responding"] = False
                await upstream.send(json.dumps({"type": "response.cancel"}))

            # Turn numbers + romanization sub-lines on the two completed-text
            # events. Streaming deltas are forwarded untouched.
            if etype == "conversation.item.input_audio_transcription.completed":
                transcript = (event.get("transcript") or "").strip()
                if transcript and lang in _WRONG_SCRIPT_LANGS and _wrong_script(transcript):
                    # Wrong-script ASR misfire: keep turn numbering aligned
                    # (grammar ignores it — no target script), but blank the
                    # transcript and flag it; the page shows a muted
                    # placeholder instead of wrong-language text. Raw text
                    # stays in the log.
                    logger.info(
                        "REALTIME user transcript wrong-script, hidden from UI: \"{}\"",
                        transcript[:60],
                    )
                    turn = tracker.note_user_transcript(transcript)
                    event["turn"] = turn
                    event["raw_transcript"] = transcript
                    event["transcript"] = ""
                    event["transcript_unclear"] = True
                    await after_turn_event(turn)
                elif transcript:
                    turn = tracker.note_user_transcript(transcript)
                    event["turn"] = turn
                    await after_turn_event(turn)
            elif etype == "response.audio_transcript.done":
                event["turn"] = tracker.turn
                transcript = event.get("transcript") or ""
                tracker.note_tutor_text(transcript)

            await browser.send_text(json.dumps(event))

    try:
        tasks = [
            asyncio.create_task(browser_to_upstream(), name="browser->upstream"),
            asyncio.create_task(upstream_to_browser(), name="upstream->browser"),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        # Surface unexpected pump errors to the page before tearing down.
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, websockets.ConnectionClosed)):
                await send_error(browser, f"proxy pump error: {exc!r}")
    finally:
        # Teardown is best-effort: turns and quota usage are already
        # persisted EAGERLY during the session, so nothing here is
        # load-bearing. ASGI test clients cancel the handler task via a
        # cancel scope the moment the client side closes (a BaseException
        # that except Exception won't catch), which can cut any of these
        # awaits short — harmless.
        #
        # The upstream is aborted rather than close()-awaited: the
        # websockets close handshake waits for TCP termination, which can
        # outlive a handler cancellation — an abrupt TCP drop is all
        # DashScope needs.
        # Cost telemetry: audio in/out seconds ≈ DashScope spend.
        logger.info(
            "REALTIME SESSION end id={} turns={} audio in={:.1f}s out={:.1f}s",
            session.id[:8], tracker.turn, meter.in_seconds, meter.out_seconds,
        )
        try:
            await meter.flush()  # remaining sub-5s usage remainder
        except BaseException:
            pass
        try:
            await browser.close()
        except BaseException:
            pass
        try:
            await session_store.flush_session(session)
        except BaseException as exc:
            if not isinstance(exc, asyncio.CancelledError):
                logger.error("Realtime session flush failed: {}", exc)
        try:
            upstream.transport.abort()
        except Exception:
            pass
