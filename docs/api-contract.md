# Debate Tutor — API Contract (v13, 2026-08-18)

Backend: FastAPI on **port 8000** (canonical). Serves built frontend at `/` (static) and JSON API under `/api`.
Frontend dev: Vite on :5173 proxying `/api` → :8000.
All endpoints return JSON. Errors: `{"detail": "..."}` with proper HTTP status.

Auth is OPTIONAL for chatting (guest mode works). Authenticated users get history + stats persisted.
Auth = `Authorization: Bearer <token>` header on any endpoint. Never 401 on chat endpoints — just skip persistence.

## Levels (debate depth)
Exactly: `beginner`, `intermediate`, `fluent`. Any other value → 422. In v13 the values map to debate depth: `beginner`=Basics, `intermediate`=Balanced, `fluent`=Expert (values unchanged for wire compatibility).

## Endpoints

### GET /api/health
→ `{ "status": "ok", "version": "13.0.0", "uptime_s": 123, "active_sessions": 2 }`

### GET /api/languages
→ `[{ "code": "zh", "name": "Chinese (Mandarin)", "native_name": "中文", "tts": "edge" | "elevenlabs", "realtime": true | false }, ...]`
The 31 target languages (28 from the contract list + cs/ms/ta matching the UI-native list; backend is source of truth via GET /api/languages).
`realtime` (v11 M1, 2026-08-08): Qwen realtime S2S voice available for this language (`app/realtime/languages.py`); `false` → route to the cascade engine below.

### WS /api/realtime/ws (v11 M1, 2026-08-08; v13 debate)
Params (query string — browser WS can't set headers): `lang`, `level`, `mode` (`ptt`|`handsfree`), `scenario_id` (optional), `native` (default `en`), `token` (optional; bad/absent = guest), `cont` (optional; `cont=1` = reconnect after a session-cap rollover (close 4000), skips the greeting — v11 M2), `profile` (optional; JSON-encoded learner profile `{interests, style}`, ≤4 KB, malformed/oversized dropped).
Browser ⇄ proxy ⇄ DashScope qwen3.5-omni realtime bridge. Binary frames = PCM16 audio (16 kHz up / 24 kHz down); text frames = OpenAI-realtime-shaped events plus `proxy.*` events (`proxy.user_transcript`, `proxy.feedback`, `proxy.session_cap`, `proxy.quota_exhausted`). Client commands: `input_audio_buffer.commit/clear`, `response.create`, `response.cancel`, `user_text`.
Close codes: 1008 bad params / unsupported language / missing key; 1011 upstream connect failed; 1013 concurrent-session cap per IP; 4000 session audio cap (client silently reconnects). 4001 daily-quota close is dead code since v12.2 (personal deploy — no limits). Completed turns persist into `messages`, so History/Progress work unchanged.

### POST /api/auth/register  `{username, password}` → `{token, user: {id, username, created_at}}` (409 if taken)
### POST /api/auth/login     `{username, password}` → `{token, user}` (401 on bad creds)
### POST /api/auth/logout    (Bearer) → `{ok: true}`
### GET  /api/auth/me        (Bearer) → `{user, stats: {total_sessions, total_messages, total_minutes, by_language: {code: {sessions, messages}}}}`
Passwords: PBKDF2-HMAC-SHA256 (stdlib hashlib, 100k iterations, per-user salt). Tokens: random 32-byte hex, expire after 30 days.

### GET /api/scenarios?language=zh
→ `[{ "id": "social-media", "title": "Is Social Media Bad for Society?", "description": "...", "icon": "📱" }, ...]`
Loaded from `app/prompts/scenarios/*.yaml`. v13: the scenario catalog is now **debate subjects** (the schema is unchanged; the `prompt` holds the coach's opening stance). Ship 9: social-media, ai-future, remote-work, money-happiness, school-start, free-will, zoos, gaming, voting. Empty selection = free debate. Language param reserved; return all.

### POST /api/chat/init  (multipart form)
Fields: `language` (debate language code), `native_language` (code), `level`, `scenario_id` (optional, empty string = free debate), `voice_id` (optional), `profile` (optional; JSON-encoded learner profile `{interests, style}`, ≤4 KB, malformed dropped, oversized → 422).
→ `{ "session_id": "...", "greeting": { <TurnPayload> } }`

### POST /api/chat  (multipart form)
Fields: `session_id`, `language`, plus EITHER `audio` (file, webm/opus) OR `text` (string, typed input — no STT call).
→ `{ "session_id": "...", "user_text": "...", "reply": { <TurnPayload> } }`
If audio STT yields empty transcript → 200 with `user_text: ""` and reply = localized "didn't catch that" (25-language canned table from v7, fallback English).

### POST /api/chat/stream  (multipart, same fields as /api/chat)
SSE stream of events: `event: token  data: {"text": "..."}` (REAL streamed LLM tokens of reply text), then `event: complete  data: {same JSON as /api/chat, reply.audio_base64 always ""}`, then `event: audio  data: {"audio_base64": "..."}` (TTS synthesized after complete — off the critical path; `: ping` comment frames every 5s during synthesis keep client timers alive), then `event: done data: {}`.

### TurnPayload
```
{
  "text": "...",               // coach's spoken counter-argument in the debate language
  "translation": "...",        // in user's native language ("" when the reply is already in it)
  "feedback": { "stance": "agree"|"partially_agree"|"disagree",
                "score": 0-100, "score_delta": -8..8,
                "counter": "...", "evidence": "...", "next": "..." } | null,
                               // debate card (null only on the greeting)
  "audio_base64": "..."        // mp3; "" on /chat/stream complete (see audio event)
}
```
Debate card semantics: `stance` judges the learner's claim (agree = essentially right, partially_agree = some truth some error, disagree = wrong or unsupported); `score` is the running debate score from the learner's viewpoint (start 50, ±8 max per turn, clamp 0-100); `score_delta` the signed change since the last turn; `counter`/`evidence`/`next` are read on screen, never spoken, always in the learner's native language.

### GET /api/history (Bearer) → `[{session_id, language, level, scenario_id, started_at, last_active, message_count}]`
### GET /api/history/{session_id} (Bearer) → `{session: {...}, messages: [{role, text, translation, grammar, created_at}]}` (the messages' `grammar` field carries the debate-card JSON; the DB column keeps its legacy name `grammar_json`)
### DELETE /api/history/{session_id} (Bearer) → `{ok: true}`
### GET /api/stats (Bearer) → same stats shape as /api/auth/me plus `recent_sessions` (last 5) and `streak_days`.
### GET /api/voices?language=zh → `[{voice_id, name, provider}]` — actually filter: per-language default ElevenLabs voice + Edge voices for edge languages; hardcoded table is fine, no live ElevenLabs call needed.

## LLM (DeepSeek, OpenAI-compatible, base https://api.deepseek.com, model from env DEEPSEEK_MODEL default `deepseek-v4-pro`; cheap internal calls use DEEPSEEK_MODEL_FAST default `deepseek-v4-flash`)
v13: debate-coach personas in `prompts/tutor.py` (depth tiers Basics/Balanced/Expert over the legacy level values). LLM returns strict JSON: `{reply, translation, feedback: {stance, score, score_delta, counter, evidence, next}|null}`. `feedback` is null ONLY on the first greeting; every debate turn gets one. The reply is spoken in the session's debate language (replies in the learner's native language when they write in it). Conversation history truncated to last 20 messages; the learner profile (`profile` JSON from init/ws) is injected into the system prompt when present — the personalization moat. Subject prompt injected when scenario_id set. Real streaming via `stream=True` for /chat/stream. Retry 3x with tenacity; on failure return a canned localized apology payload. Language-drift nudge: one cheap reply-only regeneration (`max_tokens=200`) when the reply script mismatches the learner's message.

## STT: ElevenLabs Scribe v2 (`scribe_v2`) via httpx, 1 retry.
## TTS chain: Edge-TTS is the PRIMARY provider for every language (native voice for all 31). ElevenLabs `eleven_v3` → `eleven_multilingual_v2` runs only as a fallback when edge fails (and the key is set), then edge is retried once more. EXCEPTION — languages in `ELEVENLABS_PRIMARY_LANGUAGES` (currently yue/zh/zh-TW): ElevenLabs runs FIRST, edge-tts is their fallback. Speed by level: all 1.0 (natural speed). NO SSML sent to ElevenLabs.

## Infra
- pydantic-settings config; read `.env`; every setting actually used or deleted (no dead settings).
- SQLite via aiosqlite, single connection module, WAL mode. Tables: sessions, messages, users, tokens, user_stats.
- Sessions: in-memory cache + SQLite persistence; 30-min TTL for guests; authenticated sessions persist fully.
- Middleware: CORS (env ALLOWED_ORIGINS), security headers, request-id + access log, in-memory rate limit 60 req/min/IP.
- loguru logs → `backend/logs/app.log`, 10 MB rotation.
- StaticFiles mount of `backend/app/static` at `/` (built frontend), with SPA fallback to index.html.
- pytest suite in `backend/tests/`: config, prompts, scenarios loading, auth store, chat router (mocked LLM/STT/TTS). Must pass with `pytest`.
