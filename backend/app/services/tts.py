"""Text-to-speech chain.

Order (per api-contract):
  1. Edge-TTS is the PRIMARY provider for every language (native voice
     for all 31 supported languages — free).
  2. ElevenLabs eleven_v3 → eleven_multilingual_v2 runs ONLY as a
     fallback when edge fails (and ELEVENLABS_API_KEY is set).
  3. Edge-TTS is retried once more before giving up.
  EXCEPTION — languages in ELEVENLABS_PRIMARY_LANGUAGES (yue/zh/zh-TW,
  user-directed 2026-08-04): ElevenLabs runs FIRST for them, with
  edge-tts as their fallback.

Fixes vs v7: plain text is sent to ElevenLabs — NO SSML (<speak>/<prosody>),
which ElevenLabs reads aloud as markup. Speed by level applies to Edge-TTS
rate strings; ElevenLabs receives unmodified text.
"""
import base64
import re

import edge_tts
import httpx
from loguru import logger

from ..config import get_settings

# ── Speed per level ──────────────────────────────────────────────────
# User-directed 2026-08-03: all levels at 1x (natural speed).
SPEED_MAP = {"beginner": 1.0, "intermediate": 1.0, "fluent": 1.0}

# ── Edge-TTS voices (all 28 languages, for primary + fallback use) ───
EDGE_TTS_VOICES = {
    # European
    "de": "de-DE-SeraphinaMultilingualNeural",
    "pt": "pt-BR-ThalitaMultilingualNeural",
    "pl": "pl-PL-MarekNeural",
    "sv": "sv-SE-MattiasNeural",
    "el": "el-GR-AthinaNeural",
    "nl": "nl-NL-MaartenNeural",
    "fr": "fr-FR-DeniseNeural",
    "es": "es-ES-ElviraNeural",
    "it": "it-IT-IsabellaNeural",
    "ru": "ru-RU-SvetlanaNeural",
    # Asian
    "zh": "zh-CN-YunyangNeural",
    "zh-TW": "zh-TW-YunJheNeural",
    "yue": "zh-HK-WanLungNeural",
    "ja": "ja-JP-KeitaNeural",
    "ko": "ko-KR-InJoonNeural",
    "vi": "vi-VN-NamMinhNeural",
    "th": "th-TH-NiwatNeural",
    "hi": "hi-IN-MadhurNeural",
    "id": "id-ID-ArdiNeural",
    "fil": "fil-PH-AngeloNeural",
    "bn": "bn-BD-NabanitaNeural",
    # Middle East / Africa / other
    "ar": "ar-DZ-AminaNeural",
    "tr": "tr-TR-EmelNeural",
    "he": "he-IL-AvriNeural",
    "ur": "ur-PK-AsadNeural",
    "az": "az-AZ-BabekNeural",
    "sw": "sw-KE-ZaliraNeural",
    # English — v13 user-directed (2026-08-18): British male is the default
    "en": "en-GB-RyanNeural",
    # v7 UI languages kept for native-language honesty
    "cs": "cs-CZ-AntoninNeural",
    "ms": "ms-MY-OsmanNeural",
    "ta": "ta-IN-PallaviNeural",
}

# ── English voice picker (v13, user-directed 2026-08-18): accent × gender.
# First entry is the default (British male). edge-tts voices, provider "edge".
EN_VOICE_OPTIONS = [
    {"voice_id": "en-GB-RyanNeural", "name": "🇬🇧 British male", "provider": "edge"},
    {"voice_id": "en-GB-SoniaNeural", "name": "🇬🇧 British female", "provider": "edge"},
    {"voice_id": "en-US-GuyNeural", "name": "🇺🇸 American male", "provider": "edge"},
    {"voice_id": "en-US-JennyNeural", "name": "🇺🇸 American female", "provider": "edge"},
    {"voice_id": "en-AU-WilliamNeural", "name": "🇦🇺 Australian male", "provider": "edge"},
    {"voice_id": "en-AU-NatashaNeural", "name": "🇦🇺 Australian female", "provider": "edge"},
]

# Voices that look like edge-tts names (e.g. "en-GB-RyanNeural") — distinct
# from ElevenLabs voice IDs (15-30 alphanumeric chars).
_EDGE_VOICE_RE = re.compile(r"^[a-z]{2,3}-[A-Z]{2}-[A-Za-z]+Neural$")

# ── Debate host voice (v13, user-directed 2026-08-19): the moderator speaks
# the intro in its own voice, then the debater takes over. en-only for v1 —
# other languages fall back to the debater voice (no second speaker).
MODERATOR_VOICES = {
    "en": "en-GB-SoniaNeural",  # British female host
}


def moderator_voice(language: str) -> str | None:
    """Edge voice for the debate host, or None (same-voice moderator)."""
    return MODERATOR_VOICES.get(language)

# ── Default ElevenLabs voices per language (native voices that work) ─
DEFAULT_VOICES = {
    "fr": "iFBdB4I143qF5ByX6o5A",   # Nelly — French interactive
    "es": "cTZ1Li7htNiwd1cNPgUC",   # Nestor — warm conversational Spanish
    "it": "ERE9g4sDsfBwzFT0GvPh",   # Andrea — calm warm Italian
    "ru": "t6lBrEl93uCiLR1Lgm8v",   # Alisa — natural Russian female
    "nl": "6e6TrJGLhrDGMKOy5x2i",   # Noa — fresh authentic Dutch
    "en": "iP95p4xoKVk53GoZ742B",   # Chris — charming, down-to-earth
    "zh": "zYD0xJl1ponKr8TwFBmJ",   # Jin — bright conversational Mandarin
    "zh-TW": "zYD0xJl1ponKr8TwFBmJ",  # Jin — eleven_v3 handles Taiwan Mandarin
    "yue": "Ys8vLfYx46rM7GaqQVf5",  # Lucky Chan — charming HK Cantonese
    "ko": "qWofGdsKN4woEPGCzrdX",   # Nara — warm Korean narration
    "ja": "qbfQuoRJv1T3ei3qV4bc",   # Kazuha — warm friendly Japanese
    "vi": "t3OMlxHxJtV0RvnZAY1X",   # Nga Nga — Vietnamese northern accent
    "id": "X5MLBoL2nAT0ClMkxsxn",   # Atut — conversational Indonesian
}
FALLBACK_ELEVEN_VOICE = "21m00Tcm4TlvDq8ikWAM"  # Rachel — multilingual default

# Friendly names for the /api/voices endpoint
VOICE_NAMES = {
    "iFBdB4I143qF5ByX6o5A": "Nelly",
    "cTZ1Li7htNiwd1cNPgUC": "Nestor",
    "ERE9g4sDsfBwzFT0GvPh": "Andrea",
    "t6lBrEl93uCiLR1Lgm8v": "Alisa",
    "6e6TrJGLhrDGMKOy5x2i": "Noa",
    "iP95p4xoKVk53GoZ742B": "Chris",
    "zYD0xJl1ponKr8TwFBmJ": "Jin",
    "Ys8vLfYx46rM7GaqQVf5": "Lucky Chan",
    "qWofGdsKN4woEPGCzrdX": "Nara",
    "qbfQuoRJv1T3ei3qV4bc": "Kazuha",
    "t3OMlxHxJtV0RvnZAY1X": "Nga Nga",
    "X5MLBoL2nAT0ClMkxsxn": "Atut",
    "21m00Tcm4TlvDq8ikWAM": "Rachel",
}

# ElevenLabs language codes (yue → zh for proper CJK pronunciation)
ELEVEN_LANG_CODES = {
    "en": "en", "fr": "fr", "es": "es", "de": "de", "it": "it",
    "pt": "pt", "ru": "ru", "nl": "nl", "pl": "pl", "sv": "sv",
    "el": "el", "cs": "cs", "ms": "ms",
    "zh": "zh", "zh-TW": "zh",
    # NOTE: yue intentionally omitted — Lucky Chan is a native Cantonese voice.
    # Sending language_code="zh" forces Mandarin phonemes on Cantonese text.
    # (yue/zh/zh-TW are ElevenLabs-primary via ELEVENLABS_PRIMARY_LANGUAGES.)
    "ko": "ko", "ja": "ja", "vi": "vi", "th": "th", "hi": "hi",
    "id": "id", "tr": "tr", "ar": "ar", "he": "he", "bn": "bn",
    "ur": "ur", "fil": "fil", "sw": "sw", "az": "az", "ta": "ta",
}

_ELEVEN_MODELS = ["eleven_v3", "eleven_multilingual_v2"]

VOICE_SETTINGS = {
    "stability": 0.40,
    "similarity_boost": 0.85,
    "style": 0.20,
    "use_speaker_boost": True,
}


def _speed_to_edge_rate(speed: float) -> str:
    pct = int(round((speed - 1.0) * 100))
    return f"{pct:+d}%"


def strip_annotations(text: str) -> str:
    """Remove parenthetical and bracketed notes so TTS reads clean text.

    Romanization stripping was removed deliberately — regexes for tone
    numbers and tone marks mangled legitimate words like "iPhone15" or
    "COVID19". The LLM prompt contract forbids romanization in replies;
    this strip is only the safety net for stray "(note)" / "[laughs]"
    annotations. A bare "nei5 hou2" without parens would be spoken.
    """
    if not text:
        return text
    # 1. (parenthetical) and [bracket] notes
    text = re.sub(r"\s*\([^()]*\)\s*", " ", text)
    text = re.sub(r"\s*\[[^\[\]]*\]\s*", " ", text)
    # 2. Clean orphaned punctuation and spacing
    text = re.sub(r"'(\s*)'", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,;:.!?])", r"\1", text)
    return text.strip()


async def _synthesize_edge(
    language: str, text: str, speed: float, voice_name: str | None = None
) -> str:
    """Edge-tts synthesis; `voice_name` (an edge voice id) overrides the
    per-language default — the learner-picked voice (v13)."""
    voice = voice_name or EDGE_TTS_VOICES.get(language)
    if not voice:
        raise ValueError(f"No edge-tts voice for language: {language}")
    communicate = edge_tts.Communicate(text, voice, rate=_speed_to_edge_rate(speed))
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    if not audio:
        raise RuntimeError(f"edge-tts returned no audio for {language}")
    return base64.b64encode(bytes(audio)).decode("utf-8")


async def _synthesize_eleven(text: str, language: str, voice_id: str | None) -> str:
    """ElevenLabs chain: eleven_v3 → eleven_multilingual_v2.

    Plain text only — ElevenLabs must NOT receive SSML. Raises
    RuntimeError when every model fails.
    """
    settings = get_settings()
    if not voice_id or not re.match(r"^[a-zA-Z0-9]{15,30}$", voice_id):
        voice_id = DEFAULT_VOICES.get(language, FALLBACK_ELEVEN_VOICE)

    lang_code = ELEVEN_LANG_CODES.get(language)
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    last_error: Exception | None = None
    for model_id in _ELEVEN_MODELS:
        body = {
            "text": text,
            "model_id": model_id,
            "output_format": "mp3_22050_32",
            "voice_settings": VOICE_SETTINGS,
        }
        if lang_code:
            body["language_code"] = lang_code
        try:
            async with httpx.AsyncClient(timeout=settings.tts_timeout_seconds) as client:
                resp = await client.post(
                    url,
                    headers={
                        "xi-api-key": settings.elevenlabs_api_key,
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                resp.raise_for_status()
                return base64.b64encode(resp.content).decode("utf-8")
        except Exception as exc:
            last_error = exc
            logger.warning("TTS failed with {} ({}), trying next", model_id, exc)
    raise RuntimeError(f"ElevenLabs TTS failed for {language}: {last_error}")


async def synthesize(
    text: str,
    language: str = "en",
    voice_id: str | None = None,
    level: str = "beginner",
) -> str:
    """Text → base64 mp3. Raises RuntimeError if every provider fails.

    Default chain: Edge-TTS is the PRIMARY provider for every language —
    free and reliable, with a native voice for all 31 supported languages;
    ElevenLabs runs only when edge fails (and the key is set), then edge
    is retried once. Languages in settings.elevenlabs_primary_set flip
    this: ElevenLabs runs FIRST for them, edge-tts is their fallback.
    """
    settings = get_settings()
    speed = SPEED_MAP.get(level, 1.0)
    tts_text = strip_annotations(text)
    if not tts_text:
        raise ValueError("empty text for TTS")
    # v13 voice picker: an edge voice id (…-Neural) selects the edge voice;
    # anything else is an ElevenLabs voice id (existing behavior).
    edge_voice = voice_id if voice_id and _EDGE_VOICE_RE.match(voice_id) else None
    eleven_voice_id = None if edge_voice else voice_id

    # ── ElevenLabs-primary languages (ELEVENLABS_PRIMARY_LANGUAGES) ──
    if language in settings.elevenlabs_primary_set:
        if not settings.elevenlabs_api_key:
            logger.warning(
                "ElevenLabs is primary for {} but no key is set — using edge-tts", language
            )
            try:
                return await _synthesize_edge(language, tts_text, speed)
            except Exception as exc:
                raise RuntimeError(f"TTS failed for {language}: {exc}") from exc
        try:
            return await _synthesize_eleven(tts_text, language, voice_id)
        except Exception as exc:
            logger.warning("ElevenLabs failed for {} (primary) — falling back to edge-tts", language)
            try:
                return await _synthesize_edge(language, tts_text, speed)
            except Exception as edge_exc:
                logger.error("edge-tts fallback also failed for {}: {}", language, edge_exc)
                raise RuntimeError(
                    f"TTS failed for {language}: {exc}; edge fallback: {edge_exc}"
                ) from edge_exc

    # ── 1. Edge-TTS is the primary provider for every other language ──
    try:
        return await _synthesize_edge(language, tts_text, speed, edge_voice)
    except Exception as exc:
        if not settings.elevenlabs_api_key:
            raise RuntimeError(f"TTS failed for {language}: {exc}")
        logger.warning("Edge-TTS failed for {} ({}) — falling back to ElevenLabs", language, exc)

    # ── 2. ElevenLabs chain ── (key presence already guaranteed above: the
    # edge-failure handler raises when the key is missing)
    try:
        return await _synthesize_eleven(tts_text, language, eleven_voice_id)
    except Exception as exc:
        # ── 3. Edge-TTS retried once more before giving up ──
        logger.info("TTS falling back to edge-tts for {}", language)
        try:
            return await _synthesize_edge(language, tts_text, speed, edge_voice)
        except Exception:
            raise RuntimeError(f"TTS failed for {language}: {exc}") from exc


def voice_options(language: str) -> list[dict]:
    """Voice list for /api/voices (no live calls). English exposes the
    accent × gender picker (v13, British male default); every other
    language reports its single default edge-tts voice (or the ElevenLabs
    voice for ELEVENLABS_PRIMARY_LANGUAGES)."""
    settings = get_settings()
    if language == "en":
        return list(EN_VOICE_OPTIONS)
    if language in settings.elevenlabs_primary_set:
        voice_id = DEFAULT_VOICES.get(language, FALLBACK_ELEVEN_VOICE)
        name = VOICE_NAMES.get(voice_id, voice_id)
        return [{"voice_id": voice_id, "name": name, "provider": "elevenlabs"}]
    edge_voice = EDGE_TTS_VOICES.get(language, EDGE_TTS_VOICES["en"])
    return [{"voice_id": edge_voice, "name": edge_voice, "provider": "edge"}]
