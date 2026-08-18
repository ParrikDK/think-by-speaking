"""Voices catalog — hardcoded per-language defaults (no live API call).

v13 (2026-08-18): English exposes an accent × gender picker from the
edge-tts set (British male default), plus the qwen realtime presets
(provider "realtime") for the voice-first path — Adam (male) was
live-verified against the upstream in the 2026-08-18 session.
"""
from fastapi import APIRouter

from ..models.schemas import VoiceOut
from ..services import tts

router = APIRouter(tags=["voices"])

# qwen3.5-omni realtime presets selectable per language (probe-verified
# 2026-08-18: session.update accepts these and echoes them back).
REALTIME_VOICE_OPTIONS = {
    "en": [
        {"voice_id": "Adam", "name": "🇬🇧 Male (realtime)", "provider": "realtime"},
        {"voice_id": "Jennifer", "name": "🇺🇸 Female (realtime)", "provider": "realtime"},
    ],
}


@router.get("/voices", response_model=list[VoiceOut])
async def list_voices(language: str = "en"):
    voices = list(tts.voice_options(language))
    voices.extend(REALTIME_VOICE_OPTIONS.get(language, []))
    return voices
