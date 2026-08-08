# Speak, Don't Just Read — API Contract (v8 rebuild)

Backend: FastAPI on **port 8000** (canonical). Serves built frontend at `/` (static) and JSON API under `/api`.
Frontend dev: Vite on :5173 proxying `/api` → :8000.
All endpoints return JSON. Errors: `{"detail": "..."}` with proper HTTP status.

Auth is OPTIONAL for chatting (guest mode works). Authenticated users get history + stats persisted.
Auth = `Authorization: Bearer <token>` header on any endpoint. Never 401 on chat endpoints — just skip persistence.

## Levels
Exactly: `beginner`, `intermediate`, `fluent`. Any other value → 422. No A1/B2 anywhere.

## Endpoints

### GET /api/health
→ `{ "status": "ok", "version": "8.0.0", "uptime_s": 123, "active_sessions": 2 }`

### GET /api/languages
→ `[{ "code": "zh", "name": "Chinese (Mandarin)", "native_name": "中文", "tts": "edge" | "elevenlabs", "realtime": true | false }, ...]`
The 31 target languages (28 from the contract list + cs/ms/ta matching the UI-native list; backend is source of truth via GET /api/languages).
`realtime` (v11 M1, 2026-08-08): Qwen realtime S2S voice available for this language (`app/realtime/languages.py`); `false` → route to the cascade engine below.

### WS /api/realtime/ws (v11 M1, 2026-08-08)
Params (query string — browser WS can't set headers): `lang`, `level`, `mode` (`ptt`|`handsfree`), `scenario_id` (optional), `native` (default `en`), `token` (optional; bad/absent = guest).
Browser ⇄ proxy ⇄ DashScope qwen3.5-omni realtime bridge. Binary frames = PCM16 audio (16 kHz up / 24 kHz down); text frames = OpenAI-realtime-shaped events plus `proxy.*` events (`proxy.user_transcript`, `proxy.grammar`, `proxy.session_cap`, `proxy.quota_exhausted`). Client commands: `input_audio_buffer.commit/clear`, `response.create`, `response.cancel`, `user_text`.
Close codes: 1008 bad params / unsupported language / missing key; 1011 upstream connect failed; 1013 concurrent-session cap per IP; 4000 session audio cap (client silently reconnects); 4001 daily quota exhausted (guests: `REALTIME_GUEST_TRIAL_SECONDS` per IP; users: `REALTIME_DAILY_MINUTES`). Completed turns persist into `messages`, so History/Progress work unchanged.

### POST /api/auth/register  `{username, password}` → `{token, user: {id, username, created_at}}` (409 if taken)
### POST /api/auth/login     `{username, password}` → `{token, user}` (401 on bad creds)
### POST /api/auth/logout    (Bearer) → `{ok: true}`
### GET  /api/auth/me        (Bearer) → `{user, stats: {total_sessions, total_messages, total_minutes, by_language: {code: {sessions, messages}}}}`
Passwords: PBKDF2-HMAC-SHA256 (stdlib hashlib, 100k iterations, per-user salt). Tokens: random 32-byte hex, expire after 30 days.

### GET /api/scenarios?language=zh
→ `[{ "id": "restaurant", "title": "At the Restaurant", "description": "...", "icon": "🍜" }, ...]`
Loaded from `app/prompts/scenarios/*.yaml`. Ship 8: restaurant, airport, hotel, shopping, doctor, taxi-directions, job-interview, small-talk. Language param reserved; return all.

### POST /api/chat/init  (multipart form)
Fields: `language` (target code), `native_language` (code), `level`, `scenario_id` (optional, empty string = free talk), `voice_id` (optional).
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
  "text": "...",               // tutor reply in target language
  "translation": "...",        // in user's native language
  "grammar": { "is_correct": true, "corrected_text": "...", "explanation": "..." } | null,  // null when user_text empty or nothing to correct
  "audio_base64": "..."        // mp3; "" on /chat/stream complete (see audio event)
}
```

### GET /api/history (Bearer) → `[{session_id, language, level, scenario_id, started_at, last_active, message_count}]`
### GET /api/history/{session_id} (Bearer) → `{session: {...}, messages: [{role, text, translation, grammar, created_at}]}`
### DELETE /api/history/{session_id} (Bearer) → `{ok: true}`
### GET /api/stats (Bearer) → same stats shape as /api/auth/me plus `recent_sessions` (last 5) and `streak_days`.
### GET /api/voices?language=zh → `[{voice_id, name, provider}]` — actually filter: per-language default ElevenLabs voice + Edge voices for edge languages; hardcoded table is fine, no live ElevenLabs call needed.

## LLM (DeepSeek, OpenAI-compatible, base https://api.deepseek.com, model from env DEEPSEEK_MODEL default `deepseek-v4-pro`; cheap internal calls use DEEPSEEK_MODEL_FAST default `deepseek-v4-flash`)
System prompt per level (adapt v7 `prompt/tutor.py` persona logic). LLM returns strict JSON: `{reply, translation, grammar: {is_correct, corrected_text, explanation}|null}`. The reply must be written in the same language as the learner's most recent message. Replies are raw target-language text with no romanization (the contract forbids it and nothing adds it server-side). Conversation history truncated to last 20 messages. Scenario prompt injected when scenario_id set. Real streaming via `stream=True` for /chat/stream. Retry 3x with tenacity; on failure return a canned localized apology payload. Language-drift nudge: one cheap reply-only regeneration (`max_tokens=200`) when the reply script mismatches the learner's message.

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
