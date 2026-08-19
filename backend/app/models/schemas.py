"""Pydantic schemas matching docs/api-contract.md exactly."""
import json
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field


def parse_profile(raw: Optional[str]) -> Optional[dict]:
    """Parse the learner profile JSON from a form/WS payload. Oversized or
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


# ── Auth ─────────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: str
    username: str
    created_at: str


class AuthResponse(BaseModel):
    token: str
    user: UserOut


# ── Turn payload (the coach's half of a turn) ───────────────────────

class DebateFeedback(BaseModel):
    """Post-turn debate card: stance on the learner's claim, running score,
    counter-argument, one piece of evidence, next challenge question, plus
    the Think By Speaking pillars (v13.1): logical fallacies, structure, fillers."""
    stance: str = "partially_agree"  # agree | partially_agree | disagree
    score: int = 50
    score_delta: int = 0
    counter: str = ""
    evidence: str = ""
    next: str = ""
    fallacies: list[dict] = Field(default_factory=list)  # {type, quote, note} ≤2
    structure: str = ""                                   # one structural line
    filler_count: int = 0                                 # spoken fillers (um/like)
    delivery: dict = Field(default_factory=dict)          # {pace, pitch} from audio


class TurnPayload(BaseModel):
    text: str
    translation: str = ""
    feedback: Optional[DebateFeedback] = None
    audio_base64: str = ""


class ChatInitResponse(BaseModel):
    session_id: str
    greeting: TurnPayload


class ChatResponse(BaseModel):
    session_id: str
    user_text: str
    reply: TurnPayload
    error_type: Optional[str] = None  # "silence" | "llm_failure" | "tts_failure" | None


# ── History / stats ──────────────────────────────────────────────────

class SessionSummary(BaseModel):
    session_id: str
    language: str
    level: str
    scenario_id: Optional[str] = None
    started_at: str
    last_active: str
    message_count: int


class MessageOut(BaseModel):
    role: str
    text: str
    translation: Optional[str] = None
    pronunciation: str = ""
    grammar: Optional[dict] = None
    created_at: str


class SessionDetail(BaseModel):
    session: SessionSummary
    messages: list[MessageOut]


class LanguageStat(BaseModel):
    sessions: int
    messages: int


class Stats(BaseModel):
    total_sessions: int = 0
    total_messages: int = 0
    total_minutes: int = 0
    by_language: dict[str, LanguageStat] = {}


class FullStats(Stats):
    debate: dict = Field(default_factory=dict)
    streak_days: int = 0
    recent_sessions: list[SessionSummary] = []


class MeResponse(BaseModel):
    user: UserOut
    stats: Stats


# ── Misc ─────────────────────────────────────────────────────────────

class LanguageOut(BaseModel):
    code: str
    name: str
    native_name: str
    tts: str  # "edge" | "elevenlabs"
    realtime: bool = False  # v11 M1: Qwen realtime S2S voice available


class ScenarioOut(BaseModel):
    id: str
    title: str
    description: str
    icon: str
    interests: list[str] = []


class VoiceOut(BaseModel):
    voice_id: str
    name: str
    provider: str


class HealthOut(BaseModel):
    status: str
    version: str
    uptime_s: int
    active_sessions: int
