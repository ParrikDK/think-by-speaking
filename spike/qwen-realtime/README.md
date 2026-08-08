# Spike: Qwen3.5-Omni realtime as the tutor voice path

**Status: COMPLETE — all four spike questions PASS (2026-08-07).** This rig
proved the realtime speech-to-speech path for v10: native-sounding Cantonese,
sub-second turns, clean barge-in. Keep it as the reference implementation for
Phase 2 (wiring this into the v10 app proper). It is still not production
code — do not import it from the app.

```
server.py          FastAPI app: serves the page, bridges /ws to DashScope upstream WS
static/index.html  Voice-tutor page (mic, playback, barge-in, transcripts,
                   romanization sub-lines, grammar cards, typed input, replay)
static/debug.html  Original raw test rig (fallback diagnostic)
README.md          This file
```

## Architecture (the layering principle — this is the important part)

1. **Voice layer (S2S)** — Qwen3.5-Omni realtime over WebSocket. Carries ONLY
   voice + its transcript. Persona contains voice rules only.
2. **Text layer (deterministic)** — jyutping/pinyin sub-lines computed by
   library code (`services.romanize` from the app), never by an LLM.
3. **Judgment layer (async, isolated)** — grammar cards from DeepSeek after
   each turn; JSON mode; failure means no card, never a broken conversation.

Failure hierarchy: voice keeps working no matter what the lower layers do.
Prefer reliable code over LLM-dependent behavior; prefer model SELECTION over
prompt band-aids (plus obeys the rules flash kept breaking).

## Setup

1. `DASHSCOPE_API_KEY` — Alibaba Cloud Model Studio, INTERNATIONAL site:
   <https://modelstudio.console.alibabacloud.com> (free quota for new users).
2. `DEEPSEEK_API_KEY` — optional; enables grammar cards. The key already lives
   in `v9/backend/.env`; load it without displaying it:

   ```bash
   set -a; source "/Users/parrik/Code/Language tutor AI /v9/backend/.env"; set +a
   ```

   (Without it the server logs "grammar cards disabled" once and runs fine.)
3. `websockets` must be in the **v10 backend venv** (present at 17.0.1 when
   created). Spike-only: **do not** add it to the app's requirements.txt.

## Run

```bash
set -a; source "/Users/parrik/Code/Language tutor AI /v9/backend/.env"; set +a
cd "<version-folder>/spike/qwen-realtime"          # this folder (v10 snapshot / v11 working)
DASHSCOPE_API_KEY=sk-... ../../backend/venv/bin/python server.py
```

Open <http://localhost:8899> (localhost counts as a secure context — no https
needed for the mic). Pick language (廣東話 / 普通话 / English), level
(beginner / intermediate / fluent), model (plus is default); tap the mic, talk
— or type in the dock. `SPIKE_PORT` env overrides port 8899.

## Features

- Realtime voice conversation with semantic VAD and barge-in (talk over the
  tutor, or tap the mic button to interrupt).
- **Levels** — beginner (teaches in English, weaves 1–2 target words),
  intermediate (target-language conversation, gentle corrections), fluent
  (natural chat). VAD patience is level-aware: silence_duration 1600 / 1100 /
  700 ms — beginners pause mid-sentence and must not be cut off.
- **Romanization sub-lines** under both bubbles (jyutping tone numbers for
  廣東話, tone-mark pinyin for 普通话) — library-computed, mixed text inline
  ("你好 I am Parrik" → "nei5 hou2 I am Parrik").
- **Grammar cards** — post-turn DeepSeek (`deepseek-v4-flash`, JSON mode,
  thinking disabled) judging only the target-language parts; green ✓ or
  corrected text + one-line explanation inside your bubble. yue/zh only fire
  on CJK-containing turns.
- **Typed input** — same turn pipeline as speech; queue when session is
  starting; cancels tutor speech politely when sent mid-reply.
- **Replay** — per-tutor-bubble; only one replay at a time (a new one stops
  the previous); a new live tutor response stops any replay (live takes
  precedence). Replay is local playback — it does not touch the mic/session.
- Debug drawer: per-turn latency (speech end → first audio) + raw event log.
  The server also writes a timestamped event log to stdout.

## Spike verdict (2026-08-06/07, live-tested by user)

1. **Cantonese quality — PASS.** Kiki sounds native HK by the user's ear.
2. **Language pinning — PASS.** Zero unprompted Mandarin slips; plus holds
   register. (Flash read jyutping parentheticals aloud and stumbled words —
   plus does neither; hence plus is the default.)
3. **Latency — PASS.** ~0.7–1.3 s speech-end → first audio.
4. **Barge-in — PASS.** Clean cut, no stale audio.

Bugs found & fixed during the spike (all in the page/proxy, none in the API):

- **"First syllable repeats" stutter** — the page connected the mic worklet
  straight to `AudioContext.destination` (live mic monitoring through the
  speakers → acoustic feedback loop). Fixed with a zero-gain node. Diagnosed
  via the server event log (every turn `status=completed`, zero cancels).
- **Bubble order** — the ASR `completed` event can land after the tutor's
  reply starts; the user bubble is now inserted before the in-flight tutor
  bubble.
- **100 ms playback jitter buffer** — upstream sends audio in bursts faster
  than realtime; a 30 ms floor underran at reply start.
- **Beginner-frame romanization reflex** — in the teach-in-English frame the
  model wants to write "(nei5 hou2)" after a new word (and reads it aloud).
  Mitigated by giving it an outlet ("the screen shows jyutping automatically")
  and a format ("We say 早晨 — it means good morning."). Residual risk noted:
  in an S2S model the text tokens ARE the audio script — there is no
  interception point; if a model still slips at beginner, the structural fix
  is the cascade for that mode. Watch the server log.

## Voice choices (from the qwen3.5-omni-realtime voice list in the docs)

| lang | voice | why |
|------|-------|-----|
| yue | `Kiki` | One of only two Cantonese preset voices: "a sweet Hong Kong girl best friend" — fits a warm tutor. Alternative: `Rocky` (witty Cantonese). |
| zh  | `Ethan` | The only voice described as "Standard Mandarin" (slight northern accent). Cindy/Qiao/Angel are explicitly Taiwanese-accented — wrong for 普通话. |
| en  | `Jennifer` | "Premium, cinematic-quality American female voice." (Aiden/Mione also fine.) |

To try alternatives, edit `LANG_CONFIG` in `server.py`.

## session.update payload sent (per language + level)

```json
{
  "type": "session.update",
  "session": {
    "modalities": ["text", "audio"],
    "voice": "Kiki" | "Ethan" | "Jennifer",
    "input_audio_format": "pcm",
    "output_audio_format": "pcm",
    "input_audio_transcription": { "model": "qwen3-asr-flash-realtime" },
    "turn_detection": { "type": "semantic_vad", "threshold": 0.5,
                        "silence_duration_ms": 1600 | 1100 | 700 },
    "instructions": "<LANG_CONFIG base (voice rules) + LEVELS persona>"
  }
}
```

## Protocol notes

Verified against (2026-08-06, plus live verification since):

- <https://docs.qwencloud.com/developer-guides/speech/realtime-multimodal-speech>
- <https://docs.qwencloud.com/api-reference/real-time-multimodal/client-events>
- <https://docs.qwencloud.com/api-reference/real-time-multimodal/server-events>

- Endpoint: `wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime?model=<model>`,
  `Authorization: Bearer $DASHSCOPE_API_KEY`. Models:
  `qwen3.5-omni-plus-realtime` (default), `qwen3.5-omni-flash-realtime`.
- Audio: input PCM16 16 kHz, output PCM16 24 kHz (enum `"pcm"`/`"pcm"`; one
  doc example shows `"pcm16"`/`"pcm24"` — ours is accepted).
- Output streams as `response.audio.delta` (base64 → proxy decodes to binary
  frames); assistant text as `response.audio_transcript.delta/.done`.
- Input transcription is a separate fixed ASR model; the `.completed` event
  can arrive AFTER the tutor response starts (ordering handled page-side).
  Note: ASR for Cantonese speech is noticeably weaker than the omni model's
  own understanding — the tutor understands your audio even when the user
  bubble text looks mangled. Not configurable per the docs.
- Barge-in: proxy sends `response.cancel` on `input_audio_buffer.speech_started`
  while responding (tracked via response.created/done — cancel errors when
  idle); the page flushes its playback queue on the same event.
- Typed turns: `conversation.item.create` (input_text) + `response.create`.
