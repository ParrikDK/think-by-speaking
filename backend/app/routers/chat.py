"""Chat endpoints: /chat/init, /chat, /chat/stream (SSE).

Multipart forms accepting EITHER an audio file OR a text field (text skips
STT). Auth optional — guests chat freely; Bearer users get history + stats
persisted. Never 401 here.
"""
import asyncio
import json
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from loguru import logger

from ..config import get_settings
from ..db import stats_store
from ..db.session_store import SessionData, session_store
from ..db.user_store import User
from ..models.schemas import (
    ChatInitResponse,
    ChatResponse,
    DebateFeedback,
    TurnPayload,
)
from ..prompts import get_scenario
from ..prompts.tutor import VALID_LEVELS, build_messages, silence_message
from ..routers.languages import SUPPORTED_LANGUAGES
from ..services import delivery, llm, stt, tts
from .auth import get_optional_user

router = APIRouter(prefix="/chat", tags=["chat"])

# Max typed-text length per turn (review finding: unbounded text = unbounded
# LLM/TTS spend).
MAX_TEXT_CHARS = 4000


# ── Helpers ──────────────────────────────────────────────────────────

def _validate_language(language: str) -> str:
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(400, f"Unsupported language: {language}")
    return language


def _validate_level(level: str) -> str:
    level = (level or "").lower()
    if level not in VALID_LEVELS:
        raise HTTPException(422, f"Invalid level: {level!r} — expected one of {list(VALID_LEVELS)}")
    return level


def _normalize_scenario(scenario_id: Optional[str]) -> Optional[str]:
    """Empty string = free talk; unknown ids are ignored (no injection)."""
    if not scenario_id:
        return None
    scenario_id = scenario_id.strip()
    return scenario_id if get_scenario(scenario_id) else None


def _parse_profile(raw: Optional[str]) -> Optional[dict]:
    """Parse the learner profile JSON from the form/query. Oversized or
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


# Compiled once at import — matches the _MD_PATTERNS idiom in services/llm.py.
# (parens) form first — single token ("(gam2)") OR multi-token ("(m4 goi1)" —
# live-observed leak surviving the single-token form) — then bare tokens.
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
_JYUTPING_TOKEN_RE = [
    re.compile(r"\([a-z]{1,5}[1-6](?:\s+[a-z]{1,5}[1-6])*\)", re.IGNORECASE),
    re.compile(r"\b[a-z]{1,5}[1-6]\b", re.IGNORECASE),
]


def _strip_jyutping(text: str) -> str:
    """Defense-in-depth romanization guard (v8A QA battery, 2026-08-02).

    Teaching replies occasionally leak parenthetical jyutping ('唔該 (m4 goi1)')
    despite the contract prohibition. Strip tone-number tokens from mixed CJK
    replies so the visible text AND the TTS audio never contain romanization.

    Limitation (stated honestly): the bare-token strip is only applied when
    the reply contains CJK characters — pure-English replies keep legitimate
    alphanumerics ("version3", "iPhone15") untouched. Syllable length is
    capped at 5 letters ({1,5}): every real jyutping syllable is <= 5 letters
    + tone digit (nei5, gam2, jyut6, zung6, gwong1), while longer
    alphanumerics like "version3" (7 letters) are excluded. A 6+ letter
    pinyin syllable with a tone NUMBER (e.g. "zhuang1") would slip through —
    the prompt contract is the primary defense; this guard is the safety net.
    """
    if not text or not any("一" <= c <= "鿿" for c in text):
        return text
    for pattern in _JYUTPING_TOKEN_RE:
        text = pattern.sub(" ", text)
    # A bare-token strip inside "(hou2 hou2)"-style parens leaves "()" — drop it
    text = re.sub(r"\(\s*\)", " ", text)
    text = re.sub(r"\[\s*\]", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _script_ratio(text: str) -> float:
    """Fraction of CJK characters among all letters in *text* (0..1)."""
    letters = sum(c.isalpha() for c in text)
    if letters == 0:
        return 0.0
    return len(_CJK_RE.findall(text)) / letters


def _reply_language_mismatch(level: str, user_text: str, reply: str) -> bool:
    """Intermediate/fluent mirror the learner's language — the reply must be
    in the script of the learner's message. deepseek-v4-flash occasionally
    answers an English message in the target language (conversation drift);
    this detects that so the caller can nudge-retry once.

    The reply is only flagged when the WRONG script dominates it (>50% CJK
    for a native-language message, <20% CJK for a target-language message) —
    legitimate teaching replies embed target phrases inside a native sentence
    ("You can say 你好") and must not be retried.
    """
    if level not in ("intermediate", "fluent"):
        return False
    user_cjk = _script_ratio(user_text)
    reply_cjk = _script_ratio(reply)
    if user_cjk > 0.3 and reply_cjk < 0.2:
        return True  # learner wrote target language, got a native-language reply
    if user_cjk < 0.3 and reply_cjk > 0.5:
        return True  # learner wrote in native language, got a target-language reply
    return False


def _needs_nudge(level: str, user_text: str, payload: dict) -> bool:
    """Reply-language mismatch (intermediate/fluent only).

    The old check also fired on translation/grammar drifting to the target
    script — but the reply-only regeneration cannot fix those fields, so the
    trigger wasted an LLM call and could replace a good reply with an
    unvalidated one. Drift prevention now lives in the system prompt.
    """
    return _reply_language_mismatch(level, user_text, payload.get("reply", ""))


async def _nudge_retry(messages: list[dict], level: str) -> str | None:
    """One CHEAP reply-only regeneration after a language-drift nudge.

    The original full-JSON retry cost up to 3 non-streaming LLM calls and
    frequently returned plain text (which triggered yet another enrichment
    call) — and it fired on nearly every turn. This version regenerates only
    the reply text with a small max_tokens budget, then keeps it only if the
    script now matches the learner's message. Returns the regenerated reply,
    or None to keep the original.
    """
    if not messages or messages[-1].get("role") != "user":
        return None
    nudge = (
        " IMPORTANT: answer in the SAME language as this message was written "
        "in — if it is in English, your ENTIRE reply must be in English. "
        "Reply with ONLY the spoken text — no translation, no commentary."
    )
    nudged = [*messages]
    nudged[-1] = {**nudged[-1], "content": nudged[-1]["content"] + nudge}
    reply = await llm.chat_reply_fast(nudged)
    if not reply:
        return None
    reply = llm.strip_markdown(reply)
    # The built user message carries a "[Typed]: " prefix for typed
    # Chinese/Cantonese input. The prefix skews _script_ratio below the 0.3
    # CJK threshold ("[Typed]: 你好" ≈ 0.286), which would misclassify the
    # learner as writing in the native script and ACCEPT an English retry.
    # Verify against the stripped content (ported from v8B).
    user_content = messages[-1]["content"].removeprefix("[Typed]: ")
    if _reply_language_mismatch(level, user_content, reply):
        return None
    return reply


async def _build_turn(
    payload: dict, language: str, voice_id: str, level: str,
    skip_audio: bool = False,
) -> TurnPayload:
    """LLM payload dict → TurnPayload (raw text + optional TTS audio).

    v13: the contract's grammar object is now the debate feedback card
    ({stance, score, score_delta, counter, evidence, next}).
    TTS uses Edge-TTS (primary provider for every language).

    With skip_audio=True no TTS call is made — the streaming endpoint
    delivers audio on a separate SSE "audio" event after "complete".
    """
    raw_reply = _strip_jyutping(payload["reply"])
    feedback = payload.get("feedback")
    audio_b64 = ""
    if not skip_audio:
        try:
            # TTS receives the reply text as-is (the LLM contract keeps it
            # pure natural language). Edge-TTS is primary.
            audio_b64 = await tts.synthesize(raw_reply, language, voice_id or None, level)
        except Exception as exc:
            logger.error("TTS failed: {} — returning turn without audio", exc)
    translation = payload.get("translation") or ""
    return TurnPayload(
        text=raw_reply,
        translation=translation,
        feedback=DebateFeedback(**feedback) if feedback else None,
        audio_base64=audio_b64,
    )


def _attach_delivery(turn: TurnPayload, user_text: str, audio_secs: float | None, pitch_var: float | None) -> None:
    """v13.1 audio pillars: pace (words/sec from the client-measured audio
    duration) and pitch label (varied vs monotone from the client-computed
    pitch variance). Conservative thresholds — never claim more than the
    metrics support."""
    if turn.feedback is None:
        return
    d: dict = {}
    if audio_secs and audio_secs > 0.5:
        words = len(user_text.split())
        d["pace"] = round(words / audio_secs, 1)
    if pitch_var is not None and pitch_var > 0:
        d["pitch"] = "monotone" if pitch_var < 25 else "varied"
    if d:
        turn.feedback.delivery = d


async def _silence_turn(language: str, native_language: str, voice_id: str, level: str) -> TurnPayload:
    """Localized 'didn't catch that' canned reply with audio (Edge TTS).

    Beginners can't yet understand target-language speech, so the prompt is
    spoken in their NATIVE language; intermediate/fluent get the target one.
    """
    msg_lang = native_language if level == "beginner" else language
    return await _build_turn(
        {"reply": silence_message(msg_lang), "translation": "", "feedback": None},
        language,
        voice_id,
        level,
    )


def _history_for_llm(session: SessionData) -> list[dict]:
    return [{"role": m["role"], "content": m["text"]} for m in session.messages]


def _enrichment_context(session: SessionData) -> str:
    """Build a short context string of recent debate feedback.

    Injected into the system prompt so the LLM keeps the running score and
    doesn't repeat rebuttals it already scored.
    """
    points = []
    score = None

    # Walk messages in reverse — most recent feedback first
    for m in reversed(session.messages):
        if m.get("role") != "assistant":
            continue
        feedback = m.get("grammar") or m.get("feedback")
        if isinstance(feedback, dict):
            if score is None and isinstance(feedback.get("score"), int):
                score = feedback.get("score")
            counter = feedback.get("counter", "")
            evidence = feedback.get("evidence", "")
            if counter or evidence:
                points.append(f"Counter: \"{counter}\"" + (f" — Evidence: \"{evidence}\"" if evidence else ""))
        if len(points) >= 2:
            break

    if not points and score is None:
        return ""
    head = f"Recent debate: score {score}." if score is not None else "Recent debate:"
    return head + "\n- " + "\n- ".join(reversed(points))


async def _persist_auth_turn(session: SessionData, new_messages: int) -> None:
    if session.user_id and new_messages > 0:
        for _ in range(new_messages):
            await stats_store.record_message(session.user_id)


async def _extract_user_text(
    audio: Optional[UploadFile],
    text: Optional[str],
    language: str,
) -> str:
    """Typed text wins (no STT call); otherwise transcribe the audio."""
    if text is not None and text.strip():
        text = text.strip()
        if len(text) > MAX_TEXT_CHARS:
            raise HTTPException(422, f"Text too long (max {MAX_TEXT_CHARS} chars)")
        return text
    if audio is None:
        raise HTTPException(422, "Provide either an audio file or a text field")
    audio_bytes = await audio.read()
    if len(audio_bytes) > get_settings().max_audio_bytes:
        raise HTTPException(413, "Audio too large")
    return await stt.transcribe(audio_bytes, language)


# ── POST /api/chat/init ──────────────────────────────────────────────

@router.post("/init", response_model=ChatInitResponse)
async def chat_init(
    language: str = Form(...),
    native_language: str = Form("en"),
    level: str = Form(...),
    scenario_id: Optional[str] = Form(None),
    voice_id: Optional[str] = Form(None),
    profile: Optional[str] = Form(None),
    user: Optional[User] = Depends(get_optional_user),
):
    _validate_language(language)
    level = _validate_level(level)
    if native_language not in SUPPORTED_LANGUAGES:
        native_language = "en"
    scenario = _normalize_scenario(scenario_id)
    profile_data = _parse_profile(profile)

    session = session_store.create(
        SessionData(
            language=language,
            native_language=native_language,
            level=level,
            scenario_id=scenario,
            voice_id=voice_id or "",
            user_id=user.id if user else "",
            profile=profile_data,
        )
    )
    if user:
        await stats_store.record_session_created(user.id)

    messages = build_messages(
        language, level, [], "",
        native_language=native_language, scenario_id=scenario, is_init=True,
        profile=profile_data,
    )
    payload = await llm.chat_json(messages, language, native_language=session.native_language)
    # v13 moderator: the greeting is spoken by the debate host (separate
    # voice when the language has one), the debate itself by the coach.
    moderator_id = tts.moderator_voice(language) or session.voice_id
    turn = await _build_turn(payload, language, moderator_id, level)

    session.add_message(
        "assistant", turn.text, translation=turn.translation,
    )
    await _persist_auth_turn(session, 1)

    return ChatInitResponse(session_id=session.id, greeting=turn)


# ── POST /api/chat ───────────────────────────────────────────────────

@router.post("", response_model=ChatResponse)
async def chat_turn(
    session_id: str = Form(...),
    language: str = Form(...),
    audio: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    audio_secs: Optional[float] = Form(None),
    pitch_var: Optional[float] = Form(None),
):
    _validate_language(language)
    session = await session_store.get_or_load(session_id)
    if session is None:
        raise HTTPException(404, "Session not found or expired")

    user_text = await _extract_user_text(audio, text, language)

    if not user_text:
        turn = await _silence_turn(language, session.native_language, session.voice_id, session.level)
        return ChatResponse(session_id=session_id, user_text="", reply=turn, error_type="silence")

    enrichment = _enrichment_context(session)
    messages = build_messages(
        language, session.level, _history_for_llm(session), user_text,
        native_language=session.native_language, scenario_id=session.scenario_id,
        enrichment=enrichment,
    )
    payload = await llm.chat_json(messages, language, native_language=session.native_language)
    if _needs_nudge(session.level, user_text, payload):
        retried = await _nudge_retry(messages, session.level)
        if retried is not None:
            payload = {**payload, "reply": retried}
    turn = await _build_turn(payload, language, session.voice_id, session.level)

    # v13.1 delivery pillars: fillers + audio metrics (pace, pitch) — only
    # for SPOKEN turns (typed input carries no delivery signal).
    if audio is not None and turn.feedback is not None:
        turn.feedback.filler_count = delivery.count_fillers(user_text)
        _attach_delivery(turn, user_text, audio_secs, pitch_var)

    session.add_message("user", user_text)
    session.add_message(
        "assistant", turn.text, translation=turn.translation,
        grammar=turn.feedback.model_dump() if turn.feedback else None,
    )
    await _persist_auth_turn(session, 2)

    error_type = "tts_failure" if not turn.audio_base64 else None
    return ChatResponse(session_id=session_id, user_text=user_text, user_pronunciation="", reply=turn, error_type=error_type)


# ── POST /api/chat/tts (regenerate audio for a failed turn) ──────────

@router.post("/tts")
async def regenerate_tts(
    session_id: str = Form(...),
    text: str = Form(...),
    language: str = Form(...),
):
    """Synthesize audio for a given text using the session's voice config.
    Used by the frontend retry button when TTS fails mid-turn.
    """
    _validate_language(language)
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(422, f"Text too long (max {MAX_TEXT_CHARS} chars)")
    session = await session_store.get_or_load(session_id)
    if session is None:
        raise HTTPException(404, "Session not found or expired")
    audio_b64 = await tts.synthesize(text, language, session.voice_id or None, session.level)
    return {"audio_base64": audio_b64}


# ── POST /api/chat/stream (SSE) ──────────────────────────────────────

def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post("/stream")
async def chat_turn_stream(
    session_id: str = Form(...),
    language: str = Form(...),
    audio: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    audio_secs: Optional[float] = Form(None),
    pitch_var: Optional[float] = Form(None),
):
    _validate_language(language)
    session = await session_store.get_or_load(session_id)
    if session is None:
        raise HTTPException(404, "Session not found or expired")

    user_text = await _extract_user_text(audio, text, language)

    async def event_stream():
        if not user_text:
            turn = await _silence_turn(language, session.native_language, session.voice_id, session.level)
            yield _sse("complete", ChatResponse(
                session_id=session_id, user_text="", reply=turn, error_type="silence",
            ).model_dump())
            yield _sse("done", {})
            return

        enrichment = _enrichment_context(session)
        messages = build_messages(
            language, session.level, _history_for_llm(session), user_text,
            native_language=session.native_language, scenario_id=session.scenario_id,
            enrichment=enrichment,
        )
        payload: dict | None = None
        llm_failed = False
        async for item in llm.chat_json_stream(messages, language, native_language=session.native_language):
            if isinstance(item, str):
                yield _sse("token", {"text": item})
            else:
                llm_failed = item.pop("__llm_failed", False)
                payload = item
        if payload is None:
            payload = llm.fallback_payload(language)
            llm_failed = True

        if not llm_failed and _needs_nudge(session.level, user_text, payload):
            retried = await _nudge_retry(messages, session.level)
            if retried is not None:
                payload = {**payload, "reply": retried}

        # ── "complete" fires as soon as the payload is ready — no TTS in the
        # critical path. The client renders the reply, translation and grammar
        # card immediately; audio arrives on the separate "audio" event below.
        error_type = "llm_failure" if llm_failed else None
        turn = await _build_turn(
            payload, language, session.voice_id, session.level, skip_audio=True
        )
        # v13.1 delivery pillars: fillers + audio metrics for spoken turns.
        if audio is not None and turn.feedback is not None:
            turn.feedback.filler_count = delivery.count_fillers(user_text)
            _attach_delivery(turn, user_text, audio_secs, pitch_var)
        yield _sse("complete", ChatResponse(
            session_id=session_id, user_text=user_text, reply=turn, error_type=error_type,
        ).model_dump())

        # ✅ Persist the turn right after "complete" is delivered — the reply
        # was rendered and the user may disconnect at any point during the
        # TTS phase below; persisting later would silently lose delivered
        # turns. A disconnect during LLM streaming still aborts before this
        # point (GeneratorExit at the nearest yield), so no phantom turns.
        session.add_message("user", user_text)
        session.add_message(
            "assistant", turn.text, translation=turn.translation,
            grammar=turn.feedback.model_dump() if turn.feedback else None,
        )
        await _persist_auth_turn(session, 2)

        # ── TTS after complete, with heartbeat pings every 5s so the client's
        # no-data timer never trips during synthesis. If the client
        # disconnects mid-synthesis the generator is closed — cancel the task
        # so it doesn't run orphaned to completion.
        tts_task = asyncio.create_task(
            tts.synthesize(turn.text, language, session.voice_id or None, session.level)
        )
        try:
            while not tts_task.done():
                await asyncio.wait({tts_task}, timeout=5.0)
                if not tts_task.done():
                    yield ": ping\n\n"
            audio_b64 = tts_task.result()
        except asyncio.CancelledError:
            tts_task.cancel()
            raise
        except GeneratorExit:
            tts_task.cancel()
            raise
        except Exception as exc:
            logger.error("TTS failed (post-complete): {} — audio skipped", exc)
            audio_b64 = ""
        yield _sse("audio", {"audio_base64": audio_b64})
        yield _sse("done", {})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
