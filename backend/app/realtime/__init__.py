"""Realtime speech-to-speech module (v11 M1, 2026-08-08).

Ports the proven spike (spike/qwen-realtime/server.py — live-tested GO) into
the app: a browser ⇄ proxy ⇄ DashScope qwen3.5-omni realtime bridge with
per-language personas, turn accounting + persistence, romanization
sub-lines, transcript guards, quota metering and async grammar cards.

Modules:
- languages    — which app language codes Qwen realtime S2S supports
- turns        — turn accounting + persistence into the messages table
- qwen_bridge  — the WebSocket bridge itself (upstream protocol)
The HTTP surface is app/routers/realtime.py; personas live in
app/prompts/realtime_personas.py; grammar cards in app/services/grammar.py.
"""
