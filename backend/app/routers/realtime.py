"""Realtime voice WebSocket endpoint (v11 M1, 2026-08-08).

WS /api/realtime/ws?lang=&level=&mode=ptt|handsfree&scenario_id=&native=&token=&cont=

Auth is optional (query param — browser WebSockets can't set headers):
guests get the realtime_guest_trial_seconds daily trial keyed by IP,
registered users realtime_daily_minutes per day. All validation failures
send an OpenAI-realtime-shaped error event first, then close — 1008 for
bad params/unsupported language, 4001 for quota exhaustion, 1013 when the
per-IP concurrent-connection cap is hit. `cont=1` (v11 M2) marks a
session-cap rollover reconnect: the persona is told to skip the greeting
and continue the conversation naturally. The bridge itself lives in
app/realtime/qwen_bridge.py.
"""
import json
from typing import Optional

from fastapi import APIRouter, WebSocket, HTTPException
from loguru import logger

from ..config import get_settings
from ..db import usage_store
from ..db.user_store import user_store
from ..prompts import get_scenario
from ..prompts.realtime_personas import voice_for
from ..prompts.tutor import LANGUAGE_NAMES, VALID_LEVELS
from ..realtime import qwen_bridge
from ..realtime.languages import supports_realtime
from ..realtime.turns import create_session

router = APIRouter(prefix="/realtime", tags=["realtime"])

# In-memory concurrent-connection counter per client IP
# (realtime_max_concurrent_per_ip). Process-local like the HTTP rate
# limiter — good enough for a single-process deploy.
_active_by_ip: dict[str, int] = {}


def _parse_profile(raw: Optional[str]) -> Optional[dict]:
    """Parse the learner profile JSON from the WS query. Oversized or
    malformed profiles are dropped — never fail a session over a profile."""
    if not raw or not raw.strip():
        return None
    if len(raw) > 4096:
        raise HTTPException(422, "Profile too large")
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


@router.websocket("/ws")
async def realtime_ws(
    websocket: WebSocket,
    lang: str = "yue",
    level: str = "beginner",
    mode: str = "ptt",
    scenario_id: Optional[str] = None,
    native: str = "en",
    token: Optional[str] = None,
    cont: Optional[str] = None,
    profile: Optional[str] = None,
):
    await websocket.accept()
    settings = get_settings()

    # ── validation (error event first, then close — the spike's shape) ──
    if mode not in ("ptt", "handsfree"):
        await qwen_bridge.send_error(websocket, f"unknown mode '{mode}' (ptt|handsfree)")
        await websocket.close(code=1008)
        return
    if lang not in LANGUAGE_NAMES:
        await qwen_bridge.send_error(websocket, f"unknown lang '{lang}'")
        await websocket.close(code=1008)
        return
    if not supports_realtime(lang):
        await qwen_bridge.send_error(
            websocket,
            f"realtime voice is not available for {LANGUAGE_NAMES[lang]} — "
            "this language runs on the typed/cascade engine instead",
            code="unsupported_language",
        )
        await websocket.close(code=1008)
        return
    level = (level or "").lower()
    if level not in VALID_LEVELS:
        await qwen_bridge.send_error(
            websocket, f"unknown level '{level}' (use one of: {', '.join(VALID_LEVELS)})"
        )
        await websocket.close(code=1008)
        return
    if native not in LANGUAGE_NAMES:
        native = "en"  # same coercion as /api/chat/init
    scenario = None
    scenario_prompt = None
    if scenario_id and scenario_id.strip():
        found = get_scenario(scenario_id.strip())
        if found:  # unknown ids are ignored (no injection), like /api/chat
            scenario = found["id"]
            scenario_prompt = found["prompt"]
    if not settings.dashscope_api_key:
        await qwen_bridge.send_error(
            websocket, "DASHSCOPE_API_KEY is not set on the server — realtime is unavailable"
        )
        await websocket.close(code=1008)
        return

    # ── auth: bad/absent token = guest (never rejects the connection) ──
    user = None
    if token:
        try:
            user = await user_store.get_user_by_token(token)
        except Exception:
            user = None

    client_ip = websocket.client.host if websocket.client else "unknown"

    # ── concurrent-connection cap per IP ──
    if _active_by_ip.get(client_ip, 0) >= settings.realtime_max_concurrent_per_ip:
        await qwen_bridge.send_error(
            websocket, "too many concurrent realtime sessions from this network",
            code="concurrency_cap",
        )
        await websocket.close(code=1013)
        return

    # ── quota ──
    # Daily quota enforcement DISABLED (2026-08-17, personal deploy — no
    # accounts, no limits): the guest trial (realtime_guest_trial_seconds)
    # and the registered-user daily minutes never trigger. The upstream
    # 540 s session cap still rolls the connection silently (code 4000,
    # qwen_bridge._AudioMeter) — that is a DashScope API constraint, not
    # an account limit.
    #
    # cap_seconds = (
    #     settings.realtime_daily_minutes * 60
    #     if user
    #     else settings.realtime_guest_trial_seconds
    # )
    # try:
    #     used = await usage_store.seconds_used_today(user_id, client_ip)
    # except Exception as exc:
    #     logger.error("usage_audio read failed: {}", exc)
    #     used = 0
    # remaining = cap_seconds - used
    # if remaining <= 0:
    #     await qwen_bridge.send_error(
    #         websocket,
    #         "daily realtime voice quota used up — come back tomorrow"
    #         + ("" if user else ", or create a free account for more"),
    #         code="quota_exhausted",
    #     )
    #     await websocket.close(code=4001)
    #     return
    user_id = user.id if user else ""
    profile_data = _parse_profile(profile)

    session = await create_session(
        lang, level, native, scenario, voice_for(lang), user, profile_data
    )

    _active_by_ip[client_ip] = _active_by_ip.get(client_ip, 0) + 1
    try:
        await qwen_bridge.run_bridge(
            websocket,
            lang=lang,
            level=level,
            mode=mode,
            native_language=native,
            scenario_prompt=scenario_prompt,
            session=session,
            user_id=user_id,
            client_ip=client_ip,
            profile=profile_data,
            # Quota disabled (see above) — the bridge ignores this value.
            quota_remaining_seconds=float(settings.realtime_max_audio_seconds),
            continuation=bool(cont),
        )
    finally:
        left = _active_by_ip.get(client_ip, 1) - 1
        if left > 0:
            _active_by_ip[client_ip] = left
        else:
            _active_by_ip.pop(client_ip, None)
