"""Voices catalog — hardcoded per-language defaults (no live API call).

v13 (2026-08-18): English exposes an accent × gender picker from the
edge-tts set (British male default), plus the qwen realtime presets
(provider "realtime") for the voice-first path.

NOTE (2026-08-19): the qwen realtime engine validates voices ONLY when it
produces speech — session.update echoes ANY name, then a 400
"Voice 'X' is not supported" fires at first utterance. The presets below
were verified by sending a real utterance through the bridge (speech
returned): Jennifer + Ethan work; Adam, Noah do not (Lenn also speaks,
kept out of the picker — German-market voice).
"""
from fastapi import APIRouter

from ..models.schemas import VoiceOut
from ..services import tts

router = APIRouter(tags=["voices"])

# qwen3.5-omni realtime presets selectable per language — utterance-verified
# 2026-08-19 (see module docstring for the verification method).
REALTIME_VOICE_OPTIONS = {
    "en": [
        {"voice_id": "Ethan", "name": "🇬🇧 Male (realtime)", "provider": "realtime"},
        {"voice_id": "Jennifer", "name": "🇺🇸 Female (realtime)", "provider": "realtime"},
    ],
}


@router.get("/voices", response_model=list[VoiceOut])
async def list_voices(language: str = "en"):
    voices = list(tts.voice_options(language))
    voices.extend(REALTIME_VOICE_OPTIONS.get(language, []))
    return voices
