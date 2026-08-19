"""Post-turn debate feedback cards for realtime voice sessions.

v13 (2026-08-18): repurposed from grammar-checking to debate judging. After
a completed voice turn, judge the learner's claim against evidence and
logic and return a small JSON card {stance, score, score_delta, counter,
evidence, next} — the text fields one or two sentences in the learner's
NATIVE language. The cascade path gets the same card from the main LLM via
the JSON contract; this service covers the realtime (speech-to-speech)
path, exactly as the grammar card did in v11/v12.

Uses the shared DeepSeek client + v4 flags from services.llm (cheap
deepseek_model_fast, json_object mode, thinking disabled, 15s timeout).
Never raises and returns None instead — a feedback failure must not delay
or break the voice path.
"""
from loguru import logger

from ..config import get_settings
from ..prompts.tutor import LANGUAGE_NAMES
from . import llm

_SYSTEM = (
    "You are a debate judge and fact-checker for a general debate. You are "
    "given the learner's claim, the coach's reply, and recent turns of the "
    "conversation. Judge the learner's claim against evidence and logic. "
    "Respond with JSON only: "
    "{{\"stance\": \"agree\"|\"partially_agree\"|\"disagree\", "
    "\"score\": int 0-100, \"score_delta\": int -8..8, \"counter\": string, "
    "\"evidence\": string, \"next\": string, \"fallacies\": [{{\"type\": "
    "string, \"quote\": string, \"note\": string}}], \"structure\": string}} "
    "— counter, evidence, next, fallacy notes and structure are one or two "
    "sentences in {native}. stance: agree = the claim is essentially right; "
    "partially_agree = some truth, some error; disagree = wrong or "
    "unsupported. score is the running debate score from the learner's "
    "viewpoint: start at 50, move at most ±8 from the last reported score, "
    "clamp 0-100. fallacies: at most 2 — types like strawman, ad_hominem, "
    "false_dilemma, red_herring, slippery_slope, appeal_to_authority, "
    "hasty_generalization, no_true_scotsman, circular_reasoning, other; "
    "each with a short verbatim quote from the learner's claim and a short "
    "note; empty list when none. structure: one short encouraging line on "
    "the claim's structure. When the transcript is too short or unclear to "
    "judge: stance \"partially_agree\", score_delta 0, counter \"Could you "
    "say that again — I want to debate your real claim?\", evidence \"\", "
    "next \"\", fallacies [], structure \"\"."
)


async def check(
    lang: str,
    level: str,
    native_language: str,
    user_text: str,
    tutor_text: str = "",
    history_text: str = "",
) -> dict | None:
    """Debate feedback card for one completed turn, or None when skipped/failed.

    Skips (returns None without calling the LLM): no DeepSeek key or empty
    transcript.
    """
    settings = get_settings()
    if not settings.deepseek_api_key or not user_text.strip():
        return None

    prompt_user = f'Learner claim: "{user_text}"'
    if tutor_text:
        prompt_user += f'\nCoach reply (context): "{tutor_text}"'
    if history_text:
        prompt_user += f"\nRecent turns:\n{history_text}"
    messages = [
        {"role": "system", "content": _SYSTEM.format(
            native=LANGUAGE_NAMES.get(native_language, native_language),
        )},
        {"role": "user", "content": prompt_user},
    ]
    try:
        response = await llm._get_client().chat.completions.create(
            model=settings.deepseek_model_fast,
            messages=messages,
            temperature=0.2,
            max_tokens=400,
            response_format=llm._JSON_MODE,
            extra_body=llm._THINKING_OFF,
            timeout=15.0,
        )
        content = (response.choices[0].message.content or "").strip()
        data = llm.extract_json(content)
        fallacies = []
        for f in (data.get("fallacies") or []):
            if isinstance(f, dict):
                fallacies.append({
                    "type": str(f.get("type") or "other"),
                    "quote": str(f.get("quote") or ""),
                    "note": str(f.get("note") or ""),
                })
            if len(fallacies) >= 2:
                break
        return {
            "stance": str(data.get("stance") or "partially_agree"),
            "score": int(data.get("score") or 50),
            "score_delta": int(data.get("score_delta") or 0),
            "counter": str(data.get("counter") or ""),
            "evidence": str(data.get("evidence") or ""),
            "next": str(data.get("next") or ""),
            "fallacies": fallacies,
            "structure": str(data.get("structure") or ""),
        }
    except Exception as exc:
        logger.warning("Debate feedback check failed ({}): {}", lang, exc)
        return None
