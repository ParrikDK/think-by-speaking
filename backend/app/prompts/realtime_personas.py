"""Realtime voice personas — per-language voice rules + depth personas.

v13 (2026-08-18): converted from language-tutor to debate-coach personas
(user-directed: "just generally a debate person, just so that I think by
speaking"). Per-language variety pinning, voices and VAD patience are kept;
the persona identity and level tiers are debate-flavored. Post-turn debate
feedback cards come from services/grammar.py.

Voice rules are short and speech-only (no JSON contract — the debate
happens inline in speech, and post-turn feedback cards come from
services/grammar.py). Level silence values are the VAD patience ported
from the spike: beginners pause mid-sentence, so the coach waits longer
before taking the turn.

Voices: preset names from the official qwen3.5-omni realtime voice table
(https://docs.qwencloud.com/developer-guides/speech/realtime-multimodal-speech,
fetched 2026-08-08). yue/zh/en were live-verified by ear in the spike.
Where the table documents no language-specific voice, the closest
multilingual preset is chosen and marked "TODO: verify by ear".
"""
import json

from .tutor import LANGUAGE_NAMES, VALID_LEVELS, _STYLE_PROMPTS

# ── Preset voices per language ────────────────────────────────────────
# Doc evidence quoted from the voice table (2026-08-08 fetch).
_VOICES = {
    "yue": "Kiki",      # "Cantonese - Kiki … a sweet Hong Kong girl best friend" (spike-verified)
    "zh": "Ethan",      # "Standard Mandarin with a slight northern accent" (spike-verified)
    "zh-TW": "Cindy",   # "A sweet-talking young woman from Taiwan … Chinese (Taiwanese accent)"
    "en": "Jennifer",   # "A premium, cinematic-quality American female voice" (spike-verified)
    "es": "Sonrisa",    # "A warm, outgoing Latin American woman"
    "fr": "Emilien",    # "A romantic French big brother"
    "de": "Lenn",       # "a German youth who wears suits and listens to post-punk"
    "it": "Dolce",      # "A laid-back Italian man"
    "ru": "Alek",       # "Cold like the Russian spirit — yet warm as wool beneath a coat"
    "ko": "Sohee",      # "A warm, cheerful, emotionally expressive Korean unnie"
    "vi": "Hana",       # "A mature Vietnamese woman who loves dogs"
    "id": "Rizky",      # "A young Indonesian man with a distinctive voice"
    "nl": "Griet",      # "A mature, artistic Dutch woman"
    "pl": "Jakub",      # "A charismatic, artistic young man from a Polish town"
    "fil": "Bea",       # "A sweet Filipino woman who loves coffee"
    "ms": "Chloe",      # "A Malaysian office worker"
    "ja": "Ono Anna",   # "A clever, playful childhood friend"  # TODO: verify by ear (voice id contains a space — confirm exact id against the API)
    "pt": "Andre",      # "A magnetic, natural, and steady male voice"  # TODO: verify by ear (no Portuguese-specific voice documented)
    "ar": "Marina",     # "A girl raised in a multicultural city"  # TODO: verify by ear (no Arabic-specific voice documented)
    "hi": "Roya",       # "A sporty girl with a free-spirited heart"  # TODO: verify by ear (no Hindi-specific voice documented)
    "th": "Cherry",     # "A sunny, positive, friendly, and natural young woman"  # TODO: verify by ear (no Thai-specific voice documented)
    "tr": "Arda",       # "clean, crisp, and gently warm"  # TODO: verify by ear (Turkish given name, not explicitly documented)
    "sv": "Ingrid",     # "A woman from rural Norway"  # TODO: verify by ear (closest documented Nordic; no Swedish-specific voice)
    "he": "Mione",      # "A mature, intelligent British neighbor girl"  # TODO: verify by ear (no Hebrew-specific voice documented)
    "ur": "Katerina",   # "A mature, commanding voice with rich rhythm and resonance"  # TODO: verify by ear (no Urdu-specific voice documented)
    "cs": "Eliska",     # "Every word carries Central European craftsmanship and warmth"  # TODO: verify by ear (Czech name, not explicitly documented)
}

def voice_for(lang: str) -> str:
    """Upstream preset voice for the session language (Kiki for unknown)."""
    return _VOICES.get(lang, "Kiki")


# ── Debate host voice (v13, user-directed 2026-08-19): the moderator opens
# the debate in its own voice, then hands over to the coach after turn 1
# (the bridge sends a mid-session session.update voice switch — verified
# against the upstream 2026-08-19). en-only for v1; both presets verified
# to produce speech (see voices.py docstring for the verification method).
REALTIME_MODERATOR_VOICES = {
    "en": "Jennifer",  # British/American female host; coach defaults to Ethan
}


# ── Per-language voice rules (variety pinning, spoken register, no
#    romanization aloud) ────────────────────────────────────────────────

def _romanization_ban() -> str:
    """The 'never spell pronunciations aloud' rule (no romanization UI
    exists in the debate app, so one generic rule serves every language)."""
    return (
        "never romaji, romanization, transliteration, or any spelled-out "
        "pronunciation: anything you write, you say aloud."
    )


def _base_rules(lang: str, native_name: str) -> str:
    """Short voice-rules base for one language."""
    if lang == "yue":
        # Ported verbatim from the spike (live-tested), native generalized.
        return (
            "You are a warm, sharp debate coach speaking Hong Kong Cantonese "
            "(廣東話). ALWAYS speak Hong Kong Cantonese — casual spoken HK "
            "style, never Mandarin (普通话), never written Chinese register. "
            "Never switch varieties, even if the learner switches first. Speak "
            f"only natural Cantonese words and {native_name} — {_romanization_ban()}"
        )
    if lang == "zh":
        return (
            "You are a warm, sharp debate coach speaking Standard Mandarin "
            "(普通话). ALWAYS speak Standard Mandarin — casual spoken style, never "
            "Cantonese (廣東話) or any other dialect, never written/formal "
            "register. Never switch varieties, even if the learner switches "
            f"first. Speak only natural Mandarin words and {native_name} — {_romanization_ban()}"
        )
    if lang == "zh-TW":
        return (
            "You are a warm, sharp debate coach speaking Taiwan Mandarin "
            "(繁體中文). ALWAYS speak Taiwan Mandarin — casual spoken style, never "
            "Cantonese (廣東話) or any other dialect, never written/formal "
            "register. Never switch varieties, even if the learner switches "
            f"first. Speak only natural Mandarin words and {native_name} — {_romanization_ban()}"
        )
    if lang == "en":
        return (
            "You are a warm, sharp debate coach. ALWAYS speak English; never "
            "switch to any other language."
        )
    name = LANGUAGE_NAMES.get(lang, lang)
    return (
        f"You are a warm, sharp debate coach speaking {name}. ALWAYS speak "
        f"{name} — casual, natural spoken register, how native friends "
        "actually talk, never stiff or written style. Never switch to any "
        "other language or regional variety, even if the learner switches "
        f"first. Speak only natural {name} words and {native_name} — {_romanization_ban()}"
    )


# ── Level personas (ported from the spike's LEVELS; {native} replaces the
#    hardcoded English) ────────────────────────────────────────────────

# VAD patience (semantic_vad silence_duration_ms): beginners pause
# mid-sentence, so the tutor waits longer before taking the turn.
LEVEL_SILENCE_MS = {
    "beginner": 1600,
    "intermediate": 1100,
    "fluent": 700,
}

_LEVEL_PERSONAS = {
    "beginner": (
        "The learner is new to debating; their native language is {native}. "
        "Debate at BASICS depth: plain words, one idea per turn, everyday "
        "analogies, big encouragement. Speak {lang}; if the learner writes "
        "in {native}, reply in {native} and gently steer back. When they "
        "state a belief, engage with it respectfully, challenge it gently "
        "with one simple point, and ask them to restate it in their own "
        "words. Always end with a simple question."
    ),
    "intermediate": (
        "The learner knows the basics; their native language is {native}. "
        "Debate at BALANCED depth in {lang}: plain reasoning, one idea per "
        "turn, friendly challenges — never mock. Reply in {native} when the "
        "learner writes {native}, then steer back to {lang}. Concede when "
        "they are right. End with a question that makes them defend a claim."
    ),
    "fluent": (
        "The learner is fluent in {lang} and a capable arguer. Debate at "
        "EXPERT depth: weigh evidence, steelman their position, admit "
        "uncertainty; concede when they are right. Reply in {native} when "
        "the learner writes {native}, then steer back. End with a sharp "
        "challenge question."
    ),
}


def silence_ms_for(level: str) -> int:
    return LEVEL_SILENCE_MS[level]


def build_instructions(
    lang: str,
    level: str,
    native_language: str = "en",
    scenario_prompt: str | None = None,
    continuation: bool = False,
    profile: dict | None = None,
) -> str:
    """Full `instructions` value for the realtime session.update:
    language voice rules + depth persona + optional subject injection +
    optional learner profile. `continuation` marks a session-cap rollover
    reconnect (v11 M2): the conversation is already underway, so the coach
    must not greet again."""
    if level not in VALID_LEVELS:
        raise ValueError(f"Invalid level: {level!r} (expected one of {VALID_LEVELS})")
    lang_name = LANGUAGE_NAMES.get(lang, lang)
    native_name = LANGUAGE_NAMES.get(native_language, native_language)
    parts = [
        _base_rules(lang, native_name),
        _LEVEL_PERSONAS[level].format(lang=lang_name, native=native_name),
    ]
    if scenario_prompt:
        parts.append(f"SUBJECT — debate this claim: {scenario_prompt}")
    if profile:
        parts.append(
            "LEARNER PROFILE (personalize examples and stakes — never "
            "mention the profile in what you say): "
            f"{json.dumps(profile, ensure_ascii=False)}"
        )
        style = profile.get("style")
        if style in _STYLE_PROMPTS:
            parts.append(_STYLE_PROMPTS[style])
    if continuation:
        parts.append(
            "This session continues an ongoing debate — "
            "skip any greeting and continue naturally."
        )
    return " ".join(parts)
