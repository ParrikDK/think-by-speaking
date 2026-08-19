"""Debate coach persona prompts — strict-JSON output contract, per-depth
personas, subject injection, and history truncation.

v13 conversion (user-directed 2026-08-18): the app stopped being a language
tutor and became a general debate coach — "just generally a debate person,
just so that I think by speaking." The learner picks a subject (from the
scenarios/*.yaml catalog or their own), the coach opens with a stance, and
they argue back and forth; every turn carries a feedback card (stance, score,
counter, evidence, next).

Key mechanics kept from the language tutor:
  - levels are exactly beginner / intermediate / fluent (no A1/B2 anywhere);
    anything else raises ValueError (the API layer turns that into a 422).
  - system prompt carries the strict JSON output contract:
    {reply, translation, feedback|null}.
  - subject prompt (from app/prompts/scenarios/*.yaml) is injected into the
    system message when a subject is active.
  - conversation history is truncated to the last 20 messages.
"""
import json
from typing import Optional

VALID_LEVELS = ("beginner", "intermediate", "fluent")

MAX_HISTORY_MESSAGES = 20

# ── The 28 target languages (backend is source of truth) ─────────────
LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Mandarin Chinese",
    "zh-TW": "Traditional Chinese (Taiwan)",
    "yue": "Cantonese",
    "ar": "Arabic",
    "hi": "Hindi",
    "th": "Thai",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "tr": "Turkish",
    "nl": "Dutch",
    "pl": "Polish",
    "sv": "Swedish",
    "el": "Greek",
    "he": "Hebrew",
    "bn": "Bengali",
    "ur": "Urdu",
    "fil": "Filipino",
    "sw": "Swahili",
    "az": "Azerbaijani",
    "cs": "Czech",
    "ms": "Malay",
    "ta": "Tamil",
}

# ── "I didn't catch that" canned replies (25 languages, English fallback) ──
SILENCE_MESSAGES = {
    "en": "I didn't catch that. Could you say it again, please?",
    "zh": "我没听清楚，请再说一遍好吗？",
    "zh-TW": "我沒聽清楚，請再說一遍好嗎？",
    "yue": "我聽唔清楚，可唔可以再講多次呀？",
    "fr": "Je n'ai pas compris. Pouvez-vous répéter ?",
    "ko": "잘 못 들었어요. 다시 말해 주시겠어요?",
    "ja": "聞き取れませんでした。もう一度言っていただけますか？",
    "es": "No te he entendido. ¿Puedes repetir?",
    "de": "Ich habe Sie nicht verstanden. Können Sie das wiederholen?",
    "it": "Non ho capito. Puoi ripetere?",
    "pt": "Não entendi. Pode repetir?",
    "ru": "Я не расслышал. Повторите, пожалуйста.",
    "ar": "لم أستطع سماعك. هل يمكنك التكرار؟",
    "vi": "Tôi không nghe rõ. Bạn có thể nói lại không?",
    "th": "ฉันไม่ชัดเจน ช่วยพูดอีกครั้งได้ไหม",
    "hi": "मैंने सुना नहीं। कृपया दोहराएँ।",
    "id": "Saya tidak mendengar. Tolong ulangi?",
    "ms": "Saya tak dengar. Boleh ulang?",
    "nl": "Ik heb je niet gehoord. Kun je herhalen?",
    "pl": "Nie dosłyszałem. Czy możesz powtórzyć?",
    "sv": "Jag hörde inte. Kan du upprepa?",
    "cs": "Nerozuměl jsem. Můžeš zopakovat?",
    "sw": "Sikusikia vizuri. Tafadhali rudia?",
    "bn": "শুনতে পাইনি। দয়া করে আবার বলুন।",
    "ta": "எனக்குக் கேட்கவில்லை. மீண்டும் சொல்லுங்கள்.",
    "ur": "مجھے سنائی نہیں دیا۔ براہ کرم دوبارہ کہیں۔",
}


def silence_message(language: str) -> str:
    """Localized 'didn't catch that' line, English fallback."""
    return SILENCE_MESSAGES.get(language, SILENCE_MESSAGES["en"])


# ── "Technical glitch" error messages (distinct from silence) ──────────
ERROR_MESSAGES = {
    "en": "Sorry, I hit a technical glitch. Could you try that again?",
    "zh": "抱歉，我遇到了技术问题。请再试一次好吗？",
    "zh-TW": "抱歉，我遇到了技術問題。請再試一次好嗎？",
    "yue": "唔好意思，我撞到技術問題。可唔可以再試多次？",
    "fr": "Désolé, j'ai eu un problème technique. Peux-tu réessayer ?",
    "ko": "죄송합니다. 기술적 문제가 발생했습니다. 다시 시도해 주시겠어요?",
    "ja": "すみません、技術的な問題が発生しました。もう一度試していただけますか？",
    "es": "Lo siento, tuve un problema técnico. ¿Puedes intentarlo de nuevo?",
    "de": "Entschuldigung, ich hatte ein technisches Problem. Können Sie es noch einmal versuchen?",
    "it": "Mi dispiace, ho avuto un problema tecnico. Puoi riprovare?",
    "pt": "Desculpe, tive um problema técnico. Pode tentar novamente?",
    "ru": "Извините, у меня возникла техническая неполадка. Попробуйте ещё раз.",
    "ar": "عذرًا، واجهت مشكلة فنية. هل يمكنك المحاولة مرة أخرى؟",
    "vi": "Xin lỗi, tôi gặp sự cố kỹ thuật. Bạn có thể thử lại không?",
    "th": "ขออภัย ฉันมีปัญหาทางเทคนิค คุณลองอีกครั้งได้ไหม",
    "hi": "क्षमा करें, मुझे एक तकनीकी समस्या हुई। कृपया पुनः प्रयास करें।",
    "id": "Maaf, saya mengalami masalah teknis. Bisakah kamu coba lagi?",
    "ms": "Maaf, saya ada masalah teknikal. Boleh cuba lagi?",
    "nl": "Sorry, ik had een technisch probleem. Kun je het opnieuw proberen?",
    "pl": "Przepraszam, wystąpił problem techniczny. Spróbuj ponownie?",
    "sv": "Tyvärr, jag fick ett tekniskt problem. Kan du försöka igen?",
    "cs": "Omlouvám se, došlo k technické chybě. Můžeš to zkusit znovu?",
    "sw": "Samahani, nilipata tatizo la kiufundi. Tafadhali jaribu tena?",
    "bn": "দুঃখিত, আমি একটি প্রযুক্তিগত সমস্যায় পড়েছি। আবার চেষ্টা করুন।",
    "ta": "மன்னிக்கவும், எனக்கு ஒரு தொழில்நுட்ப சிக்கல் ஏற்பட்டது. மீண்டும் முயற்சிக்கவும்.",
    "ur": "معاف کیجیے، مجھے ایک تکنیکی مسئلہ درپیش ہوا۔ براہ کرم دوبارہ کوشش کریں۔",
}


def error_message(language: str) -> str:
    """Localized 'technical glitch' line, English fallback."""
    return ERROR_MESSAGES.get(language, ERROR_MESSAGES["en"])


# ── Strict JSON output contract injected into every system prompt ────
JSON_CONTRACT = (
    "You MUST respond with a single valid JSON object and NOTHING else — "
    "no markdown fences, no commentary before or after. Exact shape:\n"
    "{\n"
    '  "reply": "<your spoken counter-argument — natural language, in the '
    'session\'s debate language>",\n'
    '  "translation": "<translation of the ENTIRE reply into the learner\'s '
    'native language; empty string when the reply is already written in the '
    'learner\'s native language>",\n'
    '  "feedback": {"stance": "agree"|"partially_agree"|"disagree", "score": 0-100, '
    '"score_delta": -8..8, "counter": "<your pushback or concession in the '
    'learner\'s native language — one or two sentences>", "evidence": "<one '
    'evidence-backed fact or strong logical point in the learner\'s native '
    'language>", "next": "<the next challenge question in the learner\'s native '
    'language — may be an empty string>", "fallacies": [{"type": "strawman"|"ad_hominem"|'
    '"false_dilemma"|"red_herring"|"slippery_slope"|"appeal_to_authority"|'
    '"hasty_generalization"|"no_true_scotsman"|"circular_reasoning"|"other", '
    '"quote": "<the learner\'s own words that commit the fallacy>", "note": "<one '
    'short line in the learner\'s native language>"}], "structure": "<one short '
    'line in the learner\'s native language on the claim\'s structure — opening '
    'hook, premise-to-conclusion flow, or evidentiary support>"} | null\n'
    "}\n"
    "Rules: feedback is null ONLY on the very first greeting message — every "
    "debate turn gets one. stance judges the accuracy of the learner's claim: "
    "agree = essentially right; partially_agree = some truth, some error; "
    "disagree = wrong or unsupported. score is the running debate score from "
    "the learner's viewpoint: start at 50, move at most ±8 per turn based on "
    "evidence quality, accuracy, and how well they defend against pushback; "
    "clamp 0-100; score_delta is the signed change since the last turn. "
    "fallacies: flag AT MOST the 2 most important fallacies in the learner's "
    "claim, each with a short verbatim quote from their words; an empty list "
    "when the claim commits none. structure: one short, encouraging line. "
    "counter, evidence, next, fallacy notes and structure are read on screen, "
    "never spoken — always in the learner's native language. The \"reply\" is "
    "read aloud by text-to-speech: pure natural language in the debate "
    "language, never romanization, never meta-words like \"Translation\" or "
    "\"Correction\". Never invent keys, never omit keys."
)


# Persona templates keyed by f"{level}{'_init' if is_init else ''}" — one
# template per persona, with {lang}/{native} as the target/native language
# names (see _persona). The RULE/IMPORTANT/REMEMBER boilerplate is written
# once per persona instead of duplicated across init/non-init branches.
_PERSONAS = {
    "fluent_init": (
        "Act as a sharp, warm debate coach and moderator who debates in "
        "{lang}. This is the very first message: name the subject, explain "
        "the format in one or two lines (back-and-forth, scored, the coach "
        "always answers back), and ask the learner to state their position "
        "FIRST — do not state your own position yet; you take your side "
        "after hearing theirs. If NO subject was provided, invite the "
        "learner to name the topic they want to debate — do not invent a "
        "subject of your own. Write reply in {lang} and its translation in "
        "{native}. "
        "RULE — if the learner writes in {native}, your ENTIRE reply is in "
        "{native}. "
        "IMPORTANT: the reply is read aloud by TTS — natural {lang} only, "
        "never romanization."
    ),
    "intermediate_init": (
        "Act as a warm, sharp debate coach and moderator debating in "
        "{lang}. This is the very first message: name the subject, explain "
        "the format in one or two lines (back-and-forth, scored, the coach "
        "always answers back), and ask the learner to state their position "
        "FIRST — do not state your own position yet; you take your side "
        "after hearing theirs. If NO subject was provided, invite the "
        "learner to name the topic they want to debate — do not invent a "
        "subject of your own. Write reply in {lang} and its translation in "
        "{native}. "
        "RULE — if the learner writes in {native}, your ENTIRE reply is in "
        "{native}. "
        "IMPORTANT: the reply is read aloud by TTS — natural {lang} only, "
        "never romanization."
    ),
    "beginner_init": (
        "Act as a warm, patient debate coach and moderator debating in "
        "{lang}. This is the very first message: name the subject in the "
        "simplest words possible, say that you two will go back and forth "
        "and the coach will always answer back, and ask the learner what "
        "they think about it first — no jargon, no lecture, and do not "
        "state your own position yet. If NO subject was provided, invite "
        "the learner to name a topic they care about — do not invent a "
        "subject of your own. Write reply in {lang} and its translation in "
        "{native}. "
        "RULE — if the learner writes in {native}, your ENTIRE reply is in "
        "{native}. "
        "IMPORTANT: the reply is read aloud by TTS — natural {lang} only, "
        "never romanization."
    ),
    "fluent": (
        "Act as a sharp, warm debate coach debating in {lang}. Engage at "
        "EXPERT depth: weigh evidence quality, spot logical fallacies, "
        "steelman the learner's position before challenging it, and admit "
        "uncertainty when the evidence is mixed. Challenge their claims "
        "with evidence, concede when they are right, and teach the thinking "
        "inside every rebuttal. End every turn with a question that makes "
        "them defend their next claim or answer your challenge. "
        "Write reply in {lang} and its translation in {native}. "
        "RULE — if the learner writes in {native} or asks for an "
        "explanation, your ENTIRE reply is in {native}. "
        "IMPORTANT: the reply is read aloud by TTS — natural {lang} only, "
        "never romanization."
    ),
    "intermediate": (
        "Act as a warm debate coach debating in {lang}. Engage at BALANCED "
        "depth: plain reasoning, one idea per turn, friendly challenges — "
        "never mock. Teach the thinking inside every rebuttal, concede when "
        "the learner is right, and end every turn with a question that makes "
        "them defend a claim. "
        "Write reply in {lang} and its translation in {native}. "
        "RULE — if the learner writes in {native} or asks for an "
        "explanation, your ENTIRE reply is in {native}. "
        "IMPORTANT: the reply is read aloud by TTS — natural {lang} only, "
        "never romanization."
    ),
    "beginner": (
        "Act as a warm, patient debate coach debating in {lang}. Engage at "
        "BASICS depth: no jargon, one idea per turn, everyday analogies "
        "(e.g. \"an argument is like a house — it needs a foundation, not "
        "just a roof\"), big encouragement. When the learner states a "
        "belief, engage with it respectfully, challenge it gently with one "
        "simple point, and ask them to restate their position in their own "
        "words. End every turn with a simple question they can answer. "
        "Write reply in {lang} and its translation in {native}. "
        "RULE — if the learner writes in {native} or asks for an "
        "explanation, your ENTIRE reply is in {native}. "
        "IMPORTANT: the reply is read aloud by TTS — natural {lang} only, "
        "never romanization."
    ),
}


# ── Shared debate rules ────────────────────────────────────────────
# Appended to every system prompt (adaptation + ethics: all personas;
# subject steering + flow: non-init turns only — the greeting opens the
# debate and teaches nothing yet). The v13 persona rewrites rely on these,
# so they must not be duplicated inside the persona strings.
_ADAPTATION_PRINCIPLE = (
    "ADAPTATION PRINCIPLE — meet the learner where they are, every turn. "
    "Match the depth of their latest claim: a vague claim gets a gentle "
    "clarify-then-challenge; a confident claim gets real pushback; a "
    "correct claim gets a \"yes, and here is why\" plus a deeper "
    "follow-up. Never repeat a point you already scored; never move on "
    "without responding to their claim. No fixed script — flow like a "
    "person."
)

_SUBJECT_ENGINE = (
    "SUBJECT STEERING — the learner picked a subject to debate. Stay on "
    "it; when a tangent comes up, acknowledge it, use it to score a "
    "point, then steer back. If the learner runs out of claims, offer a "
    "fresh angle on the same subject — a common position they may have "
    "heard, a \"what about…?\" — to keep the debate going. Spoken only — "
    "there is no UI card for this."
)

_FLOW_RULES = (
    "FLOW RULES — Always reply in the session's debate language: if the "
    "learner switches language mid-debate, acknowledge it in one line and "
    "continue in the session language — never switch. Never announce, "
    "explain, or justify the language you reply in. Open each turn by "
    "naming the learner's latest claim or answer — never open with a "
    "stale point. Teach at most one new idea per turn. The closing line "
    "is always a question that forces the learner to PRODUCE an argument, "
    "not just agree. If the learner says goodbye or ends the session, "
    "close warmly, give the final score, and drop pending questions."
)

_DEBATE_ETHICS = (
    "DEBATE ETHICS — argue ideas, never the person: no ad hominem, no "
    "mockery, no gotchas. Always steelman the learner's position — state "
    "their best version, then answer it. Ground every claim in evidence, "
    "logic, or mainstream consensus; when the evidence is mixed, say so. "
    "Concede promptly when the learner is right — a debate you never lose "
    "is a debate that never taught anything."
)


# ── Per-language register/style guidance, appended to the persona ───────
# User-directed 2026-08-03: prefer casual spoken language over formal —
# Hong Kong based, HK slang. Refer to the language as 廣東話, never 粵語.
# (Ported from v8B commit 86c0d62.)
_REGISTER_NOTES = {
    "yue": (
        "Use casual, conversational Hong Kong Cantonese — how friends "
        "actually talk, not written or formal register. Refer to the "
        "language as 廣東話, never 粵語. Feel free to use natural HK slang "
        "and Cantonese particles (e.g. 啦, 㗎, 咁, 喇, 喎) when they fit "
        "the tone, plus everyday HK expressions (e.g. 唔該/多謝, 食飯, "
        "出街, 快啲). Keep it friendly and natural, like chatting with a "
        "Hongkonger."
    ),
}


def _persona(language_code: str, level: str, native_language: str, is_init: bool) -> str:
    """Level-tuned persona paragraph (adapted from v7)."""
    lang_name = LANGUAGE_NAMES.get(language_code, language_code)
    native_name = LANGUAGE_NAMES.get(native_language, native_language)
    key = f"{level}{'_init' if is_init else ''}"
    prompt = _PERSONAS[key].format(lang=lang_name, native=native_name)
    note = _REGISTER_NOTES.get(language_code)
    if note:
        prompt = f"{prompt}\n{note}"
    return prompt


def build_system_prompt(
    language_code: str,
    level: str,
    native_language: str = "en",
    scenario_id: Optional[str] = None,
    is_init: bool = False,
    enrichment: str = "",
    profile: Optional[dict] = None,
) -> str:
    """Full system prompt: persona + optional subject + profile + enrichment +
    debate ethics + JSON contract."""
    level = level.lower()
    if level not in VALID_LEVELS:
        raise ValueError(f"Invalid level: {level!r} (expected one of {VALID_LEVELS})")

    parts = [_persona(language_code, level, native_language, is_init)]
    parts.append(_ADAPTATION_PRINCIPLE)
    if not is_init:
        parts.append(_FLOW_RULES)
        parts.append(_SUBJECT_ENGINE)

    if scenario_id:
        from . import get_scenario  # local import to avoid a cycle

        scenario = get_scenario(scenario_id)
        if scenario:
            parts.append(f"SUBJECT — debate this claim: {scenario['prompt']}")

    if profile:
        parts.append(
            "LEARNER PROFILE (personalize every example, counter-argument, and "
            "stake to this learner — never mention the profile in the reply "
            f"itself):\n{json.dumps(profile, ensure_ascii=False)}"
        )

    if enrichment:
        parts.append(f"SESSION CONTEXT (what has been scored so far — reference this in your reply):\n{enrichment}")

    parts.append(_DEBATE_ETHICS)
    parts.append(JSON_CONTRACT)
    return "\n\n".join(parts)


def build_messages(
    language_code: str,
    level: str,
    history: list[dict],
    user_text: str,
    native_language: str = "en",
    scenario_id: Optional[str] = None,
    is_init: bool = False,
    enrichment: str = "",
    profile: Optional[dict] = None,
) -> list[dict]:
    """OpenAI-style message list. History truncated to the last 20 messages."""
    system_content = build_system_prompt(
        language_code, level, native_language, scenario_id, is_init, enrichment, profile
    )
    messages = [{"role": "system", "content": system_content}]
    if not is_init:
        for msg in history[-MAX_HISTORY_MESSAGES:]:
            role = msg.get("role")
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": msg.get("content", "")})
        # Mark typed Chinese/Cantonese input so the persona never mistakes it
        # for speech (no speech signal in typed text — historical marker,
        # kept for consistency with the cascade pipeline).
        if language_code in ("zh", "zh-TW", "yue") and any("一" <= c <= "鿿" for c in user_text):
            user_text = f"[Typed]: {user_text}"
        messages.append({"role": "user", "content": user_text})
    return messages
