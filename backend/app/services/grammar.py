"""Post-turn grammar cards for realtime voice sessions.

v11 M1 (2026-08-08). Ported from the spike's async DeepSeek check
(spike/qwen-realtime/server.py): after a completed voice turn, judge the
learner's target-language attempt and return a small JSON card
{is_correct, corrected_text, explanation} — the explanation one short
sentence in the learner's NATIVE language (the spike hardcoded English).

Uses the shared DeepSeek client + v4 flags from services.llm (cheap
deepseek_model_fast, json_object mode, thinking disabled, 15s timeout).
Never raises and returns None instead — a grammar failure must not delay
or break the voice path.
"""
import re

from loguru import logger

from ..config import get_settings
from ..prompts.tutor import LANGUAGE_NAMES
from . import llm

# Friendly language names for the checker prompt (spike phrasing for yue).
_LANG_NAME = {"yue": "Cantonese (Hong Kong 廣東話)"}

# Script gate: for target languages written in a non-Latin script, a
# transcript with zero target-script chars is native-language chatter (or
# an ASR misfire the wrong-script guard already flagged) — nothing to
# correct, skip the LLM call. Ported from the spike's CJK gate and extended
# to Japanese kana / Korean hangul.
_TARGET_SCRIPT_RE = {
    "yue": re.compile(r"[一-鿿㐀-䶿]"),
    "zh": re.compile(r"[一-鿿㐀-䶿]"),
    "zh-TW": re.compile(r"[一-鿿㐀-䶿]"),
    "ja": re.compile(r"[぀-ヿ一-鿿]"),
    "ko": re.compile(r"[가-힣]"),
    "ru": re.compile(r"[Ѐ-ӿ]"),
    "ar": re.compile(r"[؀-ۿ]"),
    "he": re.compile(r"[֐-׿]"),
    "hi": re.compile(r"[ऀ-ॿ]"),
    "th": re.compile(r"[แ-๟]"),
}

_SYSTEM = (
    "You are a grammar checker for a {language} learner (level {level}), "
    "native {native} speaker. Judge ONLY the target-language parts of what "
    "they said; ignore {native} chatter. Respond with JSON: "
    "{{\"is_correct\": bool, \"corrected_text\": string, \"explanation\": "
    "string}} — explanation one short sentence in {native}. is_correct=true "
    "when the target-language attempt is correct or there is nothing to "
    "correct."
)


async def check(
    lang: str,
    level: str,
    native_language: str,
    user_text: str,
    tutor_text: str = "",
) -> dict | None:
    """Grammar card for one completed turn, or None when skipped/failed.

    Skips (returns None without calling the LLM): no DeepSeek key, empty
    transcript, or a transcript with no target-script characters for the
    script-gated languages above.
    """
    settings = get_settings()
    if not settings.deepseek_api_key or not user_text.strip():
        return None
    script_re = _TARGET_SCRIPT_RE.get(lang)
    if script_re is not None and not script_re.search(user_text):
        return None

    prompt_user = f'Learner said: "{user_text}"'
    if tutor_text:
        prompt_user += f'\nTutor replied (context): "{tutor_text}"'
    messages = [
        {"role": "system", "content": _SYSTEM.format(
            language=_LANG_NAME.get(lang, LANGUAGE_NAMES.get(lang, lang)),
            level=level,
            native=LANGUAGE_NAMES.get(native_language, native_language),
        )},
        {"role": "user", "content": prompt_user},
    ]
    try:
        response = await llm._get_client().chat.completions.create(
            model=settings.deepseek_model_fast,
            messages=messages,
            temperature=0.2,
            max_tokens=300,
            response_format=llm._JSON_MODE,
            extra_body=llm._THINKING_OFF,
            timeout=15.0,
        )
        content = (response.choices[0].message.content or "").strip()
        data = llm.extract_json(content)
        return {
            "is_correct": bool(data.get("is_correct")),
            "corrected_text": str(data.get("corrected_text") or ""),
            "explanation": str(data.get("explanation") or ""),
        }
    except Exception as exc:
        logger.warning("Grammar check failed ({}): {}", lang, exc)
        return None
