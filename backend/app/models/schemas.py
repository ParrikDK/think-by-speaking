"""Pydantic schemas matching docs/api-contract.md exactly."""
from typing import Optional

from pydantic import BaseModel, Field


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
    counter-argument, one piece of evidence, next challenge question."""
    stance: str = "partially_agree"  # agree | partially_agree | disagree
    score: int = 50
    score_delta: int = 0
    counter: str = ""
    evidence: str = ""
    next: str = ""


class TurnPayload(BaseModel):
    text: str
    translation: str = ""
    pronunciation: str = ""
    feedback: Optional[DebateFeedback] = None
    audio_base64: str = ""


class ChatInitResponse(BaseModel):
    session_id: str
    greeting: TurnPayload


class ChatResponse(BaseModel):
    session_id: str
    user_text: str
    user_pronunciation: str = ""
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


class VoiceOut(BaseModel):
    voice_id: str
    name: str
    provider: str


class HealthOut(BaseModel):
    status: str
    version: str
    uptime_s: int
    active_sessions: int
