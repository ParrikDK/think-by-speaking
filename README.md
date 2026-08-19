# Think By Speaking — think by speaking

A voice-first AI **debate coach**. Pick a subject ("Is social media bad for
society?", "Will AI take our jobs?", or any topic you bring), then argue
back and forth with a coach that pushes back with evidence, teaches the
thinking inside every rebuttal, and scores your debate — personalized to
your interests and debate style.

**The problem:** you think best by debating out loud, but nobody argues
back. Social media blocks you, echo chambers agree with you, and generic
advice doesn't know you. **The fix:** a coach that knows your interests
and always has to answer.

**Stack:** FastAPI + SQLite (aiosqlite) · React 18 + Vite · DeepSeek (LLM) ·
ElevenLabs (STT · primary TTS for Cantonese/Mandarin) · Edge-TTS (primary TTS for all other languages) ·
DashScope qwen3.5-omni (realtime speech-to-speech for hands-free mode) · Silero VAD (client-side).

---

## Run locally (development)

Prereqs: Python 3.12+, Node 20+.

```bash
# 1. Backend — configure keys
cd backend
cp .env.example .env          # then fill in your keys
python3 -m venv venv && source venv/bin/activate
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
cd ../backend && source venv/bin/activate
uvicorn app.main:app --port 8000              # http://localhost:8000
```

## Tests

```bash
cd backend && source venv/bin/activate
python -m pytest              # unit + API tests (external services mocked)
```

## Required environment (`backend/.env`)

| Key | Purpose |
|---|---|
| `ELEVENLABS_API_KEY` | Speech-to-text (Scribe v2) + TTS (primary for Cantonese/Mandarin, fallback otherwise) |
| `ELEVENLABS_PRIMARY_LANGUAGES` | Comma-separated languages that use ElevenLabs TTS first (default empty = Edge-TTS everywhere) |
| `DEEPSEEK_API_KEY` | Debate coach LLM (OpenAI-compatible API) |
| `DEEPSEEK_MODEL` | Optional, default `deepseek-v4-pro` (coach turns) |
| `DEEPSEEK_MODEL_FAST` | Optional, default `deepseek-v4-flash` (cheap internal calls, e.g. feedback card) |
| `DASHSCOPE_API_KEY` | **Required for hands-free mode** — Qwen realtime speech-to-speech bridge; without it `/api/realtime/ws` errors |
| `ALLOWED_ORIGINS` | CORS origins, comma-separated |

See `backend/.env.example` for the full list.

## Deploy (when ready)

Everything needed is in `deploy/`:

- **Docker:** `docker compose -f deploy/docker-compose.yml up --build` → serves on :8000
- **VPS + Caddy:** `deploy/Caddyfile` (auto-HTTPS reverse proxy → :8000) and
  `deploy/tutor.service` (systemd unit). Copy the repo to `/opt/tutor`,
  create the venv, `systemctl enable --now tutor`, point Caddy at your domain.

The SQLite database lives in `backend/` locally and in the `tutor-data`
volume under Docker.

## Features

- ⚔️ **Debate mode**: pick a subject (9 starter subjects + free debate) and argue with a coach that challenges your claims
- 📈 **Debate scoring**: every turn earns a score card — stance, counter-argument, one piece of evidence, next challenge
- 🎯 **Personalized to you**: your interests and debate style (devil's advocate / Socratic / encouraging) shape every session — the coach's examples, stakes, and challenges bend toward you
- 🗣️ **Voice-first**: speak your arguments — real-time speech-to-text, natural voice replies, replay at 0.5× / 1× / 2×
- 🎙️ **Hands-free mode**: on-device Silero VAD auto-detects end of speech, barge-in support — runs on the Qwen realtime speech-to-speech bridge (26 of the 31 languages; the rest fall back to the cascade engine)
- ⌨️ **Typed input mode** — text chat with the same coach
- 👤 Optional accounts: session history, resume, progress dashboard, streaks
- 🌍 31 debate languages, UI translated into 28 languages
