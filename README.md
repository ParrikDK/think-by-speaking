# Speak, Don't Just Read

Voice-first AI language tutor. Speak with an AI tutor in 28 languages — real-time
speech-to-text, a level-aware tutor persona, grammar correction, and natural
text-to-speech replies.
Hands-free mode with on-device voice-activity detection. Typed input works too.

**Stack:** FastAPI + SQLite (aiosqlite) · React 18 + Vite · DeepSeek (LLM) ·
ElevenLabs (STT · primary TTS for Cantonese/Mandarin) · Edge-TTS (primary TTS for all other languages) · Silero VAD (client-side).

---

## Run locally (development)

Prereqs: Python 3.12+, Node 20+.

```bash
# 1. Backend — configure keys
cd backend
cp .env.example .env          # then fill in your keys
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 2. Frontend (second terminal)
cd frontend
npm install
npm run dev                   # http://localhost:5173 (proxies /api → :8000)
```

## Run locally (production-style, single server)

```bash
cd frontend && npm install && npm run build   # builds into backend/app/static
cd ../backend && source .venv/bin/activate
uvicorn app.main:app --port 8000              # http://localhost:8000
```

## Tests

```bash
cd backend && source .venv/bin/activate
python -m pytest              # unit + API tests (external services mocked)
```

## Required environment (`backend/.env`)

| Key | Purpose |
|---|---|
| `ELEVENLABS_API_KEY` | Speech-to-text (Scribe v2) + TTS (primary for Cantonese/Mandarin, fallback otherwise) |
| `ELEVENLABS_PRIMARY_LANGUAGES` | Comma-separated languages that use ElevenLabs TTS first (default empty = Edge-TTS everywhere) |
| `DEEPSEEK_API_KEY` | Tutor LLM (OpenAI-compatible API) |
| `DEEPSEEK_MODEL` | Optional, default `deepseek-v4-pro` (tutor turns) |
| `DEEPSEEK_MODEL_FAST` | Optional, default `deepseek-v4-flash` (cheap internal calls, e.g. nudge retry) |
| `ALLOWED_ORIGINS` | CORS origins, comma-separated |

See `backend/.env.example` for the full list.

## Deploy (when ready — not required now)

Everything needed is in `deploy/`:

- **Docker:** `docker compose -f deploy/docker-compose.yml up --build` → serves on :8000
- **VPS + Caddy:** `deploy/Caddyfile` (auto-HTTPS reverse proxy → :8000) and
  `deploy/tutor.service` (systemd unit). Copy the repo to `/opt/tutor`,
  create the venv, `systemctl enable --now tutor`, point Caddy at your domain.

The SQLite database lives in `backend/` locally and in the `tutor-data`
volume under Docker.

## Features

- 🎙️ Voice conversation loop: speak → STT → tutor → TTS reply with translation
- ⌨️ Typed input mode — text chat with the same tutor
- 🗣️ Hands-free mode: on-device Silero VAD auto-detects end of speech, barge-in support
- 📚 8 role-play scenarios (restaurant, airport, job interview, …) + free talk
- 📈 Grammar correction with explanations, woven into every reply
- 👤 Optional accounts: session history, resume, progress dashboard, streaks
- 🌍 UI translated into 28 languages
- ⏯️ Replay tutor audio at 0.5× / 1× / 2×
