"""Voices catalog — hardcoded per-language defaults (no live API call)."""
from fastapi import APIRouter

from ..models.schemas import VoiceOut
from ..services import tts

router = APIRouter(tags=["voices"])


@router.get("/voices", response_model=list[VoiceOut])
async def list_voices(language: str = "en"):
    return tts.voice_options(language)
