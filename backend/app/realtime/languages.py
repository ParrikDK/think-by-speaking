"""Realtime voice routing — which app languages Qwen realtime S2S supports.

v11 M1 (2026-08-08). Source of truth for the realtime/cascade split; the
/api/languages endpoint exposes this as a per-language `realtime` flag so
the frontend routes without duplicating the list.

Verified against the official qwen3.5-omni realtime voice table
(https://docs.qwencloud.com/developer-guides/speech/realtime-multimodal-speech,
fetched 2026-08-08): every preset voice lists the same 29 output languages —
Chinese (incl. Cantonese), English, French, German, Russian, Italian,
Spanish, Portuguese, Japanese, Korean, Thai, Indonesian, Arabic, Vietnamese,
Turkish, Finnish, Polish, Hindi, Dutch, Czech, Urdu, Tagalog, Swedish,
Danish, Hebrew, Icelandic, Malay, Norwegian, Persian.

Mapped onto the app's 31 codes: zh-TW runs on Chinese voices (Taiwanese-
accented presets exist), fil runs on Tagalog, yue is native. Greek,
Bengali, Swahili, Azerbaijani and Tamil have no realtime voice → those
sessions stay on the cascade (typed/recorded) engine.
"""

REALTIME_LANGS: frozenset[str] = frozenset({
    "en", "es", "fr", "de", "it", "pt", "ru", "ja", "ko",
    "zh", "zh-TW", "yue",
    "ar", "hi", "th", "vi", "id", "tr", "nl", "pl", "sv",
    "he", "ur", "fil", "ms", "cs",
})

# App codes with no Qwen realtime voice — the cascade path keeps serving
# them. Documented for the routing decision, not enforced here.
CASCADE_ONLY_LANGS: frozenset[str] = frozenset({"el", "bn", "sw", "az", "ta"})


def supports_realtime(code: str) -> bool:
    """True when the language can run a realtime speech-to-speech session."""
    return code in REALTIME_LANGS
