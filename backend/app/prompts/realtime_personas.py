"""Realtime voice personas — per-language voice rules + level personas.

v11 M1 (2026-08-08). Ported from the spike's LANG_CONFIG / LEVELS
(spike/qwen-realtime/server.py) with two generalizations:

- the learner's native language is interpolated ({native}) instead of the
  spike's hardcoded English;
- every realtime-supported language gets a voice-rules base, not just
  yue/zh/en.

Voice rules are short and speech-only (no JSON contract — corrections
happen inline in speech, and post-turn grammar cards come from
services/grammar.py). Level silence values are the VAD patience ported
from the spike: beginners pause mid-sentence, so the tutor waits longer
before taking the turn.

Voices: preset names from the official qwen3.5-omni realtime voice table
(https://docs.qwencloud.com/developer-guides/speech/realtime-multimodal-speech,
fetched 2026-08-08). yue/zh/en were live-verified by ear in the spike.
Where the table documents no language-specific voice, the closest
multilingual preset is chosen and marked "TODO: verify by ear".
"""
from .tutor import LANGUAGE_NAMES, VALID_LEVELS

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

# Languages whose sessions show an automatic romanization sub-line under
# the tutor's words (services/romanize supports exactly these) — the
# persona may point at the screen instead of spelling pronunciations aloud.
_ROMANIZED_LANGS = {"yue": "jyutping", "zh": "pinyin", "zh-TW": "pinyin"}


def voice_for(lang: str) -> str:
    """Upstream preset voice for the session language (Kiki for unknown)."""
    return _VOICES.get(lang, "Kiki")


# ── Per-language voice rules (variety pinning, spoken register, no
#    romanization aloud) ────────────────────────────────────────────────

def _romanization_ban(lang: str) -> str:
    """The 'never spell pronunciations aloud' rule; Chinese varieties get
    the screen-shows-romanization outlet (the spike's proven phrasing)."""
    system = _ROMANIZED_LANGS.get(lang)
    if system:
        return (
            f"never {system}, tone marks, tone numbers, or any romanized "
            f"spelling: the learner's screen already shows {system} under "
            "your words automatically, and anything you write, you say aloud."
        )
    return (
        "never romaji, romanization, transliteration, or any spelled-out "
        "pronunciation: anything you write, you say aloud."
    )


def _base_rules(lang: str, native_name: str) -> str:
    """Short voice-rules base for one language."""
    if lang == "yue":
        # Ported verbatim from the spike (live-tested), native generalized.
        return (
            "You are a warm, patient Cantonese (廣東話) tutor. ALWAYS speak Hong "
            "Kong Cantonese (廣東話) — casual spoken HK style, never Mandarin "
            "(普通话), never written Chinese register. Never switch varieties, "
            "even if the learner switches first. Speak only natural Cantonese "
            f"words and {native_name} — {_romanization_ban(lang)}"
        )
    if lang == "zh":
        return (
            "You are a warm, patient Mandarin (普通话) tutor. ALWAYS speak Standard "
            "Mandarin — casual spoken style, never Cantonese (廣東話) or any other "
            "dialect, never written/formal register. Never switch varieties, even "
            f"if the learner switches first. Speak only natural Mandarin words and "
            f"{native_name} — {_romanization_ban(lang)}"
        )
    if lang == "zh-TW":
        return (
            "You are a warm, patient Mandarin (繁體中文) tutor. ALWAYS speak Taiwan "
            "Mandarin — casual spoken style, never Cantonese (廣東話) or any other "
            "dialect, never written/formal register. Never switch varieties, even "
            "if the learner switches first. Speak only natural Mandarin words and "
            f"{native_name} — {_romanization_ban(lang)}"
        )
    if lang == "en":
        return (
            "You are a warm, patient English tutor and conversation partner. "
            "ALWAYS speak English; never switch to any other language."
        )
    name = LANGUAGE_NAMES.get(lang, lang)
    return (
        f"You are a warm, patient {name} tutor. ALWAYS speak {name} — casual, "
        "natural spoken register, how native friends actually talk, never stiff "
        "or written style. Never switch to any other language or regional "
        f"variety, even if the learner switches first. Speak only natural {name} "
        f"words and {native_name} — {_romanization_ban(lang)}"
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
        "The learner is a COMPLETE BEGINNER whose native language is {native}. "
        "Teach in {native}: speak almost entirely {native}, weaving ONE or TWO "
        "new target-language words or short phrases into each turn with their "
        "meaning in {native} — chosen from what the learner just said, never a "
        "fixed list. Introduce a word in this exact shape: 'We say 早晨 — "
        "it means good morning.' Never add a pronunciation in "
        "brackets{outlet}. Keep turns short (1-3 "
        "sentences). Always end with a simple question they can answer using "
        "words they have already met. Praise attempts warmly. If their "
        "attempt comes back garbled or half-right, re-model the word once "
        "and invite another try — never say they were wrong."
    ),
    "intermediate": (
        "The learner can already converse — speak the target language with "
        "them and keep the conversation flowing naturally. Correct real errors "
        "gently and briefly (a short explanation in {native} when helpful), but "
        "let trivial slips pass — never kill the flow correcting trivia. End "
        "every turn with a question that makes them PRODUCE the target "
        "language. If they switch to {native}, reply in {native}, then gently "
        "steer back into the target language."
    ),
    "fluent": (
        "The learner is fluent — be a natural conversation partner speaking at "
        "a normal pace about real topics, with light humour when it fits. Keep "
        "the flow; correct only genuine errors, briefly. End turns with open "
        "questions that keep them talking. If they switch to {native}, answer "
        "in {native} briefly, then steer back into the target language."
    ),
}

# The beginner "never brackets" clause ends with the screen outlet only for
# the languages whose UI actually shows romanization (see _ROMANIZED_LANGS).
_OUTLET = " — the screen shows it automatically"


def silence_ms_for(level: str) -> int:
    return LEVEL_SILENCE_MS[level]


def build_instructions(
    lang: str,
    level: str,
    native_language: str = "en",
    scenario_prompt: str | None = None,
    continuation: bool = False,
) -> str:
    """Full `instructions` value for the realtime session.update:
    language voice rules + level persona + optional scenario injection.
    `continuation` marks a session-cap rollover reconnect (v11 M2): the
    conversation is already underway, so the tutor must not greet again."""
    if level not in VALID_LEVELS:
        raise ValueError(f"Invalid level: {level!r} (expected one of {VALID_LEVELS})")
    native_name = LANGUAGE_NAMES.get(native_language, native_language)
    outlet = _OUTLET if lang in _ROMANIZED_LANGS else ""
    parts = [
        _base_rules(lang, native_name),
        _LEVEL_PERSONAS[level].format(native=native_name, outlet=outlet),
    ]
    if scenario_prompt:
        parts.append(f"SCENARIO — role-play this situation: {scenario_prompt}")
    if continuation:
        parts.append(
            "This session continues an ongoing practice conversation — "
            "skip any greeting and continue naturally."
        )
    return " ".join(parts)
