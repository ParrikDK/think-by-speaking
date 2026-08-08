#!/usr/bin/env python3
"""Spike: browser <-> local proxy <-> DashScope Qwen3.5-Omni realtime bridge.

Standalone (no app imports). Run:  python server.py   then open http://localhost:8899

Protocol reference (verified 2026-08-06):
  - https://docs.qwencloud.com/developer-guides/speech/realtime-multimodal-speech
  - https://docs.qwencloud.com/api-reference/real-time-multimodal/client-events
  - https://docs.qwencloud.com/api-reference/real-time-multimodal/server-events

2026-08-07: levels (beginner/intermediate/fluent) with level-aware VAD patience;
timestamped upstream event log to stdout (stutter diagnosis).
2026-08-07 (b): romanization sub-lines (via the app's services.romanize), typed
input (user_text), async per-turn grammar cards via DeepSeek, SPIKE_PORT env.
"""

import asyncio
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

# Romanization sub-lines reuse the app's proven module (jyutping w/ tone
# numbers for yue, tone-mark pinyin for zh, "" for en; mixed text inline).
# Optional: if the import fails the spike still runs, just without
# romanization (logged once at startup).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "app"))
try:
    from services.romanize import romanize as _romanize
    _ROMANIZE_ERR = None
except Exception as exc:
    _romanize = None
    _ROMANIZE_ERR = exc


# The fixed ASR display model (qwen3-asr-flash-realtime, not configurable per
# the docs) occasionally turns Cantonese speech into a completely foreign
# script — observed live 2026-08-07: spoken Cantonese → "หรือว่าเนเน่ เดดดี้มา"
# (Thai). The omni model still understood the audio (its reply was correct);
# only the bubble text is garbage. No language-hint parameter exists, so we
# detect wrong-script transcripts deterministically and flag them for the UI.
_WRONG_SCRIPT_RE = re.compile(
    "[ᄀ-ᅟ가-힣぀-ヿЀ-ӿ؀-ۿ֐-׿ऀ-ॿঀ-৾ஂ-௿แ-๟]"
)

# Same misfire, Latin-script flavor: 唔使 → "Hmm, ça va." (French, 2026-08-08).
# Accented Latin letters (ç, é, à, ü, ñ…) essentially never appear in real
# English or Chinese transcripts, so they mark a misdetected language too.
_DIACRITIC_RE = re.compile("[À-ɏ]")


def _wrong_script(text: str) -> bool:
    """True when a yue/zh-session transcript looks like the wrong language:
    foreign-script chars or accented Latin, and no CJK at all (any CJK present
    = plausible transcript, keep it)."""
    if any("一" <= c <= "鿿" for c in text):
        return False
    return bool(_WRONG_SCRIPT_RE.search(text) or _DIACRITIC_RE.search(text))

DASHSCOPE_REALTIME_URL = "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime"
API_KEY = os.environ.get("DASHSCOPE_API_KEY", "").strip()
PORT = int(os.environ.get("SPIKE_PORT", "8899"))

# Grammar cards (async, post-turn). Missing key -> disabled, logged once.
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
LANG_NAME = {
    "yue": "Cantonese (Hong Kong 廣東話)",
    "zh": "Mandarin Chinese",
    "en": "English",
}
CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
GRAMMAR_SYSTEM = (
    "You are a grammar checker for a {language} learner (level {level}), "
    "native English speaker. Judge ONLY the target-language parts of what "
    "they said; ignore English chatter. Respond with JSON: "
    "{{\"is_correct\": bool, \"corrected_text\": string, \"explanation\": "
    "string}} — explanation one short sentence in English. is_correct=true "
    "when the target-language attempt is correct or there is nothing to "
    "correct."
)

# Plus only (2026-08-07): user testing confirmed flash is the weak tier — it
# read jyutping parentheticals aloud despite the persona and stumbled words
# ('job'); plus does neither. Flash removed from the allowlist entirely.
DEFAULT_MODEL = "qwen3.5-omni-plus-realtime"
ALLOWED_MODELS = {
    "qwen3.5-omni-plus-realtime",
}

# Per-language preset voice + variety-pinning rules (persona level parts come
# from LEVELS below). Voices from the qwen3.5-omni-realtime voice list:
#   yue -> "Kiki" ("Cantonese - Kiki", a sweet Hong Kong girl voice). Alt: "Rocky".
#   zh  -> "Ethan" (only explicitly standard-Mandarin voice; Cindy/Qiao/Angel
#          are Taiwanese-accented).
#   en  -> "Jennifer" ("premium, cinematic-quality American female voice").
LANG_CONFIG = {
    "yue": {
        "voice": "Kiki",
        "base": (
            "You are a warm, patient Cantonese (廣東話) tutor. ALWAYS speak Hong "
            "Kong Cantonese (廣東話) — casual spoken HK style, never Mandarin "
            "(普通话), never written Chinese register. Never switch varieties, "
            "even if the learner switches first. Speak only natural Cantonese "
            "words and English — never jyutping, pinyin, tone numbers, or any "
            "romanized spelling: the learner's screen already shows jyutping "
            "under your words automatically, and anything you write, you say "
            "aloud."
        ),
    },
    "zh": {
        "voice": "Ethan",
        "base": (
            "You are a warm, patient Mandarin (普通话) tutor. ALWAYS speak Standard "
            "Mandarin — casual spoken style, never Cantonese (廣東話) or any other "
            "dialect, never written/formal register. Never switch varieties, even "
            "if the learner switches first. Speak only natural Mandarin words and "
            "English — never pinyin, tone marks, tone numbers, or any romanized "
            "spelling: the learner's screen already shows pinyin under your words "
            "automatically, and anything you write, you say aloud."
        ),
    },
    "en": {
        "voice": "Jennifer",
        "base": (
            "You are a warm, patient English tutor and conversation partner. "
            "ALWAYS speak English; never switch to any other language."
        ),
    },
}

# Levels, adapted from v9's personas (backend/app/prompts/tutor.py) for a pure
# voice realtime session — no JSON contract, corrections happen inline in speech.
# silence_ms = VAD patience: beginners pause mid-sentence, so the tutor waits
# longer before taking the turn (v9's VAD lessons applied to semantic_vad).
LEVELS = {
    "beginner": {
        "silence_ms": 1600,
        "persona": (
            "The learner is a COMPLETE BEGINNER whose native language is English. "
            "Teach in English: speak almost entirely English, weaving ONE or TWO "
            "new target-language words or short phrases into each turn with their "
            "English meaning — chosen from what the learner just said, never a "
            "fixed list. Introduce a word in this exact shape: 'We say 早晨 — "
            "it means good morning.' Never add a pronunciation in "
            "brackets — the screen shows it automatically. Keep turns short (1-3 "
            "sentences). Always end with a simple question they can answer using "
            "words they have already met. Praise attempts warmly. If their "
            "attempt comes back garbled or half-right, re-model the word once "
            "and invite another try — never say they were wrong."
        ),
    },
    "intermediate": {
        "silence_ms": 1100,
        "persona": (
            "The learner can already converse — speak the target language with "
            "them and keep the conversation flowing naturally. Correct real errors "
            "gently and briefly (a short explanation in English when helpful), but "
            "let trivial slips pass — never kill the flow correcting trivia. End "
            "every turn with a question that makes them PRODUCE the target "
            "language. If they switch to English, reply in English, then gently "
            "steer back into the target language."
        ),
    },
    "fluent": {
        "silence_ms": 700,
        "persona": (
            "The learner is fluent — be a natural conversation partner speaking at "
            "a normal pace about real topics, with light humour when it fits. Keep "
            "the flow; correct only genuine errors, briefly. End turns with open "
            "questions that keep them talking. If they switch to English, answer "
            "in English briefly, then steer back into the target language."
        ),
    },
}
DEFAULT_LEVEL = "beginner"

app = FastAPI(title="qwen-realtime spike")
STATIC_DIR = Path(__file__).parent / "static"


def log(*args):
    """Timestamped line to stdout -> captured by the background task log."""
    print(f"[{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}]", *args, flush=True)


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


# Original test rig, kept as the fallback diagnostic page.
@app.get("/debug.html")
async def debug():
    return FileResponse(STATIC_DIR / "debug.html")


def build_session_update(lang: str, level: str, mode: str = "handsfree") -> dict:
    """session.update payload. Field names per the qwen3.5-omni realtime docs.

    Audio format values: the guide's canonical example and the server's own
    session.created echo both use "pcm"/"pcm" (input = PCM16 16 kHz, output =
    PCM16 24 kHz). One API-reference example shows "pcm16"/"pcm24" instead —
    if the server rejects "pcm", try those. See README.
    """
    cfg = LANG_CONFIG[lang]
    lvl = LEVELS[level]
    return {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "voice": cfg["voice"],
            "input_audio_format": "pcm",
            "output_audio_format": "pcm",
            # Enables user-speech transcription (separate ASR model, not
            # configurable per docs). Events: conversation.item.input_audio_transcription.*
            "input_audio_transcription": {"model": "qwen3-asr-flash-realtime"},
            # 2026-08-07 push-to-talk: null disables VAD — the client drives
            # turns with input_audio_buffer.commit + response.create.
            # handsfree: semantic_vad (recommended for the qwen3.5-omni-realtime
            # series; only it supports semantic_vad). silence 200-6000 ms.
            "turn_detection": (
                None if mode == "ptt" else {
                    "type": "semantic_vad",
                    "threshold": 0.5,
                    "silence_duration_ms": lvl["silence_ms"],
                }
            ),
            "instructions": cfg["base"] + " " + lvl["persona"],
        },
    }


async def send_error(browser: WebSocket, message: str):
    """Send an OpenAI-realtime-shaped error event the page can render."""
    try:
        await browser.send_text(json.dumps({
            "type": "error",
            "error": {"type": "spike_proxy_error", "code": "proxy", "message": message},
        }))
    except Exception:
        pass


@app.websocket("/ws")
async def ws_endpoint(browser: WebSocket, lang: str = "yue", model: str = DEFAULT_MODEL,
                      level: str = DEFAULT_LEVEL, mode: str = "ptt"):
    await browser.accept()

    if mode not in ("ptt", "handsfree"):
        await send_error(browser, f"unknown mode '{mode}' (ptt|handsfree)")
        await browser.close(code=1008)
        return
    if lang not in LANG_CONFIG:
        await send_error(browser, f"unknown lang '{lang}' (use one of: {', '.join(LANG_CONFIG)})")
        await browser.close(code=1008)
        return
    if model not in ALLOWED_MODELS:
        await send_error(browser, f"unknown model '{model}' (use one of: {', '.join(sorted(ALLOWED_MODELS))})")
        await browser.close(code=1008)
        return
    if level not in LEVELS:
        await send_error(browser, f"unknown level '{level}' (use one of: {', '.join(LEVELS)})")
        await browser.close(code=1008)
        return
    if not API_KEY:
        await send_error(
            browser,
            "DASHSCOPE_API_KEY is not set in the server environment. "
            "Get a key at modelstudio.console.alibabacloud.com, then: "
            "export DASHSCOPE_API_KEY=sk-... and restart server.py",
        )
        await browser.close(code=1008)
        return

    # --- connect upstream ------------------------------------------------
    upstream = None
    try:
        upstream = await websockets.connect(
            f"{DASHSCOPE_REALTIME_URL}?model={model}",
            additional_headers={"Authorization": f"Bearer {API_KEY}"},
            max_size=None,        # audio frames can be large
            open_timeout=15,
            ping_interval=20,     # keepalive through idle stretches
        )
    except Exception as exc:
        await send_error(browser, f"failed to connect to DashScope: {exc!r}")
        await browser.close(code=1011)
        return

    await upstream.send(json.dumps(build_session_update(lang, level, mode)))
    log(f"SESSION start lang={lang} level={level} model={model} mode={mode}")

    # True while the model has a response in flight (response.created .. response.done).
    # Needed because response.cancel errors when no response is active.
    # turn = completed user-utterance counter (ASR transcript or typed text);
    # turns[turn] = {"user", "tutor", "response_done", "grammar_sent"} for the
    # grammar-card trigger; bg = in-flight grammar tasks.
    state = {"responding": False, "first_audio_at": None, "audio_deltas": 0, "audio_bytes": 0,
             "turn": 0, "turns": {}, "done_before_transcript": False, "bg": set()}

    def romanize_text(text: str) -> str:
        """Never raises; '' when romanization is unavailable or n/a (en)."""
        if not _romanize or not text:
            return ""
        try:
            return _romanize(text, lang) or ""
        except Exception:
            return ""

    async def grammar_card(turn: int, user_text: str, tutor_text: str):
        """POST the finished turn to DeepSeek; on success send proxy.grammar.
        Any failure is logged and skipped — never breaks the session."""
        prompt_user = f'Learner said: "{user_text}"'
        if tutor_text:
            prompt_user += f'\nTutor replied (context): "{tutor_text}"'
        payload = {
            "model": "deepseek-v4-flash",
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "messages": [
                {"role": "system", "content": GRAMMAR_SYSTEM.format(
                    language=LANG_NAME[lang], level=level)},
                {"role": "user", "content": prompt_user},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    DEEPSEEK_URL,
                    headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                    json=payload,
                )
                r.raise_for_status()
                content = str(r.json()["choices"][0]["message"]["content"])
            # Tolerant parse: strip code fences if the model wrapped the JSON.
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", content).strip()
            data = json.loads(content)
            is_correct = bool(data.get("is_correct"))
            await browser.send_text(json.dumps({
                "type": "proxy.grammar",
                "turn": turn,
                "is_correct": is_correct,
                "corrected_text": str(data.get("corrected_text") or ""),
                "explanation": str(data.get("explanation") or ""),
            }))
            log(f"GRAMMAR turn={turn} is_correct={is_correct}")
        except Exception as exc:
            log(f"GRAMMAR turn={turn} failed: {exc!r}")

    def maybe_fire_grammar(turn: int):
        """Fire the DeepSeek check once both halves of a turn exist: the user
        transcript and a non-cancelled response.done for that turn."""
        if not DEEPSEEK_API_KEY:
            return
        rec = state["turns"].get(turn)
        if not rec or rec["grammar_sent"] or not rec["response_done"] or not rec["user"]:
            return
        rec["grammar_sent"] = True
        # For CJK target languages, pure-English chatter needs no correction.
        if lang in ("yue", "zh") and not CJK_RE.search(rec["user"]):
            log(f"GRAMMAR turn={turn} skipped (no CJK in user transcript)")
            return
        task = asyncio.create_task(grammar_card(turn, rec["user"], rec["tutor"]))
        state["bg"].add(task)
        task.add_done_callback(state["bg"].discard)

    def note_user_transcript(text: str):
        """Register a completed user utterance (ASR transcript or typed text)."""
        state["turn"] += 1
        state["turns"][state["turn"]] = {
            "user": text,
            "tutor": "",
            # Rare order: response.done landed before this transcript.
            "response_done": state["done_before_transcript"],
            "grammar_sent": False,
        }
        state["done_before_transcript"] = False
        maybe_fire_grammar(state["turn"])

    # No echo guard (removed 2026-08-07): the "false speech_started on reply
    # start" theory was disproved by the event log — the stutter was the page's
    # mic-monitoring feedback loop, fixed client-side. semantic_vad has fired
    # zero false triggers since; a guard would only delay real barge-ins.

    async def browser_to_upstream():
        """Mic PCM16 chunks -> input_audio_buffer.append; text cmds passthrough."""
        while True:
            msg = await browser.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data:
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
                # Guard against cancelling nothing: upstream errors on that.
                if ctype == "response.cancel" and state["responding"]:
                    log("BROWSER->UP response.cancel (manual interrupt)")
                    # Clear the flag so a user_text right behind it doesn't
                    # send a duplicate cancel (which upstream would reject).
                    state["responding"] = False
                    await upstream.send(json.dumps({"type": "response.cancel"}))
                elif ctype in ("input_audio_buffer.commit", "input_audio_buffer.clear",
                               "response.create"):
                    # Push-to-talk: the client drives turns manually. Only
                    # meaningful when the session runs with VAD off (ptt mode).
                    if mode == "ptt":
                        log(f"BROWSER->UP {ctype}")
                        await upstream.send(json.dumps({"type": ctype}))
                elif ctype == "user_text":
                    # Typed input: same turn pipeline as speech, minus the mic.
                    text = (cmd.get("text") or "").strip()
                    if not text:
                        continue
                    note_user_transcript(text)
                    log(f"BROWSER->UP user_text turn={state['turn']}: \"{text[:80]}\"")
                    # The page renders the user bubble ONLY from this echo.
                    await browser.send_text(json.dumps({
                        "type": "proxy.user_transcript",
                        "transcript": text,
                        "romanization": romanize_text(text),
                        "turn": state["turn"],
                    }))
                    if state["responding"]:
                        log("user_text while responding -> response.cancel (typed barge-in)")
                        state["responding"] = False
                        await upstream.send(json.dumps({"type": "response.cancel"}))
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
                    log("UP response.audio.delta #1 (first audio)")
                pcm = base64.b64decode(event.get("delta") or b"")
                state["audio_deltas"] += 1
                state["audio_bytes"] += len(pcm)
                if state["audio_deltas"] <= 4:
                    log(f"UP audio.delta #{state['audio_deltas']} "
                        f"t+{now - state['first_audio_at']:.3f}s {len(pcm)}B")
                if pcm:
                    await browser.send_bytes(pcm)
                continue

            # Compact log of every non-audio event (stutter/order diagnosis).
            if etype in ("response.audio_transcript.delta",):
                pass  # too chatty; the .done carries the full text
            elif etype == "response.audio_transcript.done":
                log(f"UP {etype}: \"{event.get('transcript', '')[:80]}\"")
            elif etype == "conversation.item.input_audio_transcription.completed":
                log(f"UP user transcript: \"{event.get('transcript', '')[:80]}\"")
            elif etype == "input_audio_buffer.speech_started":
                t0 = state["first_audio_at"]
                since = f"{time.monotonic() - t0:.2f}s after first audio" if t0 else "no audio yet"
                log(f"UP speech_started (responding={state['responding']}, {since})")
            elif etype.startswith(("rate_limits", "session.", "conversation.item.created",
                                   "response.output_item", "response.content_part",
                                   "input_audio_buffer.committed")):
                pass  # noise for this diagnosis
            else:
                log(f"UP {etype}")

            if etype == "response.created":
                state["responding"] = True
                state["first_audio_at"] = None
                state["audio_deltas"] = 0
                state["audio_bytes"] = 0
            elif etype == "response.done":
                state["responding"] = False
                status = (event.get("response") or {}).get("status", "?")
                log(f"UP response.done status={status} "
                    f"audio: {state['audio_deltas']} deltas / {state['audio_bytes']}B")
                if status != "cancelled":
                    rec = state["turns"].get(state["turn"])
                    if rec is not None:
                        rec["response_done"] = True
                        maybe_fire_grammar(state["turn"])
                    else:
                        # This turn's user transcript has not landed yet;
                        # attach the done to the next transcript that does.
                        state["done_before_transcript"] = True
            elif etype == "input_audio_buffer.speech_started" and state["responding"]:
                # Barge-in: cancel the in-flight response when the user talks
                # over it. The page flushes its playback queue on the same event.
                log("UP speech_started -> sending response.cancel (barge-in)")
                state["responding"] = False
                await upstream.send(json.dumps({"type": "response.cancel"}))

            # Turn numbers + romanization sub-lines on the two completed-text
            # events. Streaming deltas are forwarded untouched.
            if etype == "conversation.item.input_audio_transcription.completed":
                transcript = (event.get("transcript") or "").strip()
                if transcript and lang in ("yue", "zh") and _wrong_script(transcript):
                    # Wrong-script ASR misfire: keep turn numbering aligned
                    # (grammar ignores it — no CJK), but blank the transcript
                    # and flag it; the page shows a muted placeholder instead
                    # of wrong-language text. Raw text stays in the log.
                    log(f"UP user transcript wrong-script, hidden from UI: \"{transcript[:60]}\"")
                    note_user_transcript(transcript)
                    event["turn"] = state["turn"]
                    event["raw_transcript"] = transcript
                    event["transcript"] = ""
                    event["transcript_unclear"] = True
                elif transcript:
                    note_user_transcript(transcript)
                    event["turn"] = state["turn"]
                    event["romanization"] = romanize_text(transcript)
            elif etype == "response.audio_transcript.done":
                event["turn"] = state["turn"]
                transcript = event.get("transcript") or ""
                event["romanization"] = romanize_text(transcript)
                rec = state["turns"].get(state["turn"])
                if rec is not None:
                    rec["tutor"] = transcript

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
        log("SESSION end")
        try:
            await upstream.close()
        except Exception:
            pass
        try:
            await browser.close()
        except Exception:
            pass


if __name__ == "__main__":
    if not API_KEY:
        print("WARNING: DASHSCOPE_API_KEY not set — page will serve, but /ws will error.")
    if _ROMANIZE_ERR is not None:
        print(f"NOTE: romanization unavailable ({_ROMANIZE_ERR!r}) — continuing without it.")
    if not DEEPSEEK_API_KEY:
        print("NOTE: DEEPSEEK_API_KEY not set — grammar cards disabled.")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
