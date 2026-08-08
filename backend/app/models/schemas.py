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


# ── Turn payload (the tutor's half of a turn) ───────────────────────

class Grammar(BaseModel):
    is_correct: bool
    corrected_text: str = ""
    explanation: str = ""
    pronunciation: str = ""


class TurnPayload(BaseModel):
    text: str
    translation: str = ""
    pronunciation: str = ""
    grammar: Optional[Grammar] = None
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
