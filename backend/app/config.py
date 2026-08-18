"""Application settings (pydantic-settings, reads backend/.env).

Every setting declared here is consumed somewhere in the codebase —
no dead settings. See .env.example for the documented list.

v10 (2026-08-06): DeepSeek retired deepseek-chat / deepseek-reasoner /
deepseek-flash on 2026-07-24 — defaults moved to the v4 names
(deepseek-v4-pro for tutor turns, deepseek-v4-flash for cheap internal
calls) and warn_on_retired_models() flags stale configured names at
startup without crashing.

v11 M1 (2026-08-08): DashScope realtime speech-to-speech settings
(qwen3.5-omni realtime bridge) — upstream URL/key, per-session audio cap,
guest trial / daily quota, concurrent-connection cap per IP.
"""
from functools import lru_cache
from pathlib import Path

from loguru import logger
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ directory — anchor so relative paths work from any CWD
BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Retired by DeepSeek on 2026-07-24 → their current replacements.
RETIRED_DEEPSEEK_MODELS = {
    "deepseek-chat": "deepseek-v4-pro",
    "deepseek-reasoner": "deepseek-v4-pro",
    "deepseek-flash": "deepseek-v4-flash",
}


class Settings(BaseSettings):
    # ── API keys ──
    elevenlabs_api_key: str = ""
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-pro"
    # Cheap internal calls (language-drift nudge retry) use the fast model.
    deepseek_model_fast: str = "deepseek-v4-flash"

    # ── App ──
    environment: str = "development"  # "production" disables /docs
    host: str = "0.0.0.0"
    port: int = 8000  # canonical port
    allowed_origins: str = "http://localhost:5173,http://localhost:3000"
    log_level: str = "INFO"

    # ── Database ──
    database_url: str = "sqlite:///./debate_tutor.db"

    # ── Sessions ──
    session_ttl_minutes: int = 30      # guest session TTL
    flush_interval_seconds: int = 10   # SQLite write-behind interval

    # ── Auth ──
    token_ttl_days: int = 30

    # ── Limits ──
    max_audio_bytes: int = 25 * 1024 * 1024  # 25 MB upload cap
    rate_limit_per_minute: int = 60

    # ── Outbound timeouts (seconds) ──
    llm_timeout_seconds: float = 45.0
    llm_stream_retries: int = 2  # number of retry attempts for streaming LLM calls
    tts_timeout_seconds: float = 30.0
    stt_timeout_seconds: float = 30.0

    # ── Realtime speech-to-speech (v11 M1, 2026-08-08) ──
    # DashScope qwen3.5-omni realtime bridge (see app/realtime/).
    dashscope_api_key: str = ""
    dashscope_realtime_url: str = "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime"
    # Upstream caps a session at 600s of audio — roll the connection early.
    realtime_max_audio_seconds: int = 540
    realtime_guest_trial_seconds: int = 120  # guest trial, per IP per day
    realtime_daily_minutes: int = 30         # registered users, per day
    realtime_max_concurrent_per_ip: int = 2
    # Display-ASR model for user-speech bubbles inside the realtime session.
    # qwen3-asr-flash misrecognizes Cantonese (wrong-script or wrong chars
    # while the omni model understands the audio). gummy-realtime-v1 is the
    # better tier documented for the omni-realtime series (docs, 2026-07-02);
    # flip back to qwen3-asr-flash-realtime if upstream rejects it.
    realtime_asr_model: str = "gummy-realtime-v1"

    # ── TTS ──
    # Edge-TTS is the primary provider for every language (native voices
    # for all 31); ElevenLabs is only a fallback when edge fails.
    # Languages in ELEVENLABS_PRIMARY_LANGUAGES (comma-separated) flip
    # this: ElevenLabs runs FIRST for them, edge-tts is their fallback.
    elevenlabs_primary_languages: str = ""

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def database_path(self) -> str:
        """Filesystem path of the SQLite database."""
        return self.database_url.replace("sqlite:///", "")

    @property
    def elevenlabs_primary_set(self) -> set[str]:
        """Language codes that use ElevenLabs as their primary TTS."""
        return {c.strip() for c in self.elevenlabs_primary_languages.split(",") if c.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


def warn_on_retired_models(settings: Settings) -> None:
    """Loud startup warning when a configured DeepSeek model was retired
    (2026-07-24). Never crashes — names the replacement so the operator
    can fix .env; the API itself will reject the old name with an error."""
    for attr in ("deepseek_model", "deepseek_model_fast"):
        name = getattr(settings, attr)
        replacement = RETIRED_DEEPSEEK_MODELS.get(name)
        if replacement:
            logger.warning(
                "⚠️  {}={!r} was RETIRED by DeepSeek on 2026-07-24 and will fail "
                "— set it to {!r} (see .env.example)",
                attr.upper(), name, replacement,
            )
