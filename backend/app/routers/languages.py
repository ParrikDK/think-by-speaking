"""Languages catalog — the supported target languages (backend is source of truth).

v11 M1 (2026-08-08): each language carries a `realtime` flag (Qwen
realtime S2S support per app/realtime/languages.py) so the frontend routes
between the realtime and cascade engines without duplicating the list.
"""
from fastapi import APIRouter

from ..config import get_settings
from ..models.schemas import LanguageOut
from ..prompts.tutor import LANGUAGE_NAMES
from ..realtime.languages import supports_realtime

router = APIRouter(tags=["languages"])

NATIVE_NAMES = {
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "it": "Italiano",
    "pt": "Português",
    "ru": "Русский",
    "ja": "日本語",
    "ko": "한국어",
    "zh": "中文（普通话）",
    "zh-TW": "中文（繁體）",
    "yue": "粵語",
    "ar": "العربية",
    "hi": "हिन्दी",
    "th": "ไทย",
    "vi": "Tiếng Việt",
    "id": "Bahasa Indonesia",
    "tr": "Türkçe",
    "nl": "Nederlands",
    "pl": "Polski",
    "sv": "Svenska",
    "el": "Ελληνικά",
    "he": "עברית",
    "bn": "বাংলা",
    "ur": "اردو",
    "fil": "Filipino",
    "sw": "Kiswahili",
    "az": "Azərbaycan",
    "cs": "Čeština",
    "ms": "Bahasa Melayu",
    "ta": "தமிழ்",
}

SUPPORTED_LANGUAGES = list(LANGUAGE_NAMES.keys())


@router.get("/languages", response_model=list[LanguageOut])
async def list_languages():
    langs = [
        LanguageOut(
            code=code,
            name=LANGUAGE_NAMES[code],
            native_name=NATIVE_NAMES.get(code, code),
            tts="elevenlabs" if code in get_settings().elevenlabs_primary_set else "edge",
            realtime=supports_realtime(code),
        )
        for code in SUPPORTED_LANGUAGES
    ]
    # Sort by English name so both language picker screens show the same order
    langs.sort(key=lambda l: l.name)
    return langs
