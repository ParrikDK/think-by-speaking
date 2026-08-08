"""ElevenLabs Scribe v2 speech-to-text via httpx, with 1 retry.

Returns the transcribed text, or "" when the audio is empty, silent, or
the service fails — the chat layer turns "" into the localized
'didn't catch that' canned reply.
"""
import asyncio

import httpx
from loguru import logger

from ..config import get_settings

STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"

# ElevenLabs Scribe v2 language code mapping.
# Scribe accepts ISO 639-1 (2-letter) and some ISO 639-3 (3-letter) codes.
# Our internal codes that aren't valid Scribe codes get mapped to a close
# alternative, or None is sent so Scribe auto-detects.
STT_LANG_CODES = {
    "en": "en",
    "es": "es",
    "fr": "fr",
    "de": "de",
    "it": "it",
    "pt": "pt",
    "ru": "ru",
    "ja": "ja",
    "ko": "ko",
    # Chinese variants: Scribe accepts "zh" for Mandarin Chinese.
    # yue (Cantonese): Scribe natively supports "yue" (ISO 639-3, high
    # accuracy tier) — sending it explicitly beats auto-detect, which can
    # flip to a dominant other language mid-conversation. Forcing "zh"
    # instead made Scribe run Mandarin ASR on Cantonese speech → empty.
    "zh": "zh",
    "yue": "yue",
    "zh-TW": "zh",
    "ar": "ar",
    "hi": "hi",
    "th": "th",
    "vi": "vi",
    "id": "id",
    "tr": "tr",
    "nl": "nl",
    "pl": "pl",
    "sv": "sv",
    "el": "el",
    "he": "he",
    "bn": "bn",
    "ur": "ur",
    # Filipino — Scribe uses "tl" (ISO 639-1 for Tagalog)
    "fil": "tl",
    "sw": "sw",
    "az": "az",
    "cs": "cs",
    "ms": "ms",
    "ta": "ta",
}


async def transcribe(audio_bytes: bytes, language: str) -> str:
    """Transcribe audio (webm/opus). Never raises; "" on failure or silence."""
    settings = get_settings()
    if not audio_bytes:
        logger.warning("STT skipped: empty audio (0 bytes)")
        return ""
    if not settings.elevenlabs_api_key:
        logger.error("STT failed: ELEVENLABS_API_KEY is not set")
        return ""

    # Map internal code to Scribe-compatible code; None → auto-detect
    scribe_code = STT_LANG_CODES.get(language)
    audio_size = len(audio_bytes)
    logger.info("STT request: lang={}, scribe_code={}, audio={} bytes", language, scribe_code, audio_size)

    last_error = None
    for attempt in range(2):  # initial try + 1 retry
        if attempt > 0:
            await asyncio.sleep(0.5)
        try:
            data = {
                "model_id": "scribe_v2",
                "tag_audio_events": "false",
            }
            if scribe_code:
                data["language_code"] = scribe_code
            async with httpx.AsyncClient(timeout=settings.stt_timeout_seconds) as client:
                resp = await client.post(
                    STT_URL,
                    headers={"xi-api-key": settings.elevenlabs_api_key},
                    files={"file": ("audio.webm", audio_bytes, "audio/webm")},
                    data=data,
                )
                resp.raise_for_status()
                result = resp.json()
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("STT attempt {}/2 failed: {}", attempt + 1, last_error)
            continue

        text = (result.get("text") or "").strip()
        if text:
            logger.info("STT success: lang={}, text={} chars", language, len(text))
            return text
        last_error = "empty transcript"
        logger.warning("STT attempt {}/2: empty transcript", attempt + 1)

    logger.error("STT failed after 2 attempts: {}", last_error)
    return ""
