"""Voice-guided setup (v13.1, "grandma mode" v1).

Research-informed design (2026-08-19): numbered verbal menus ("say one for
AI jobs, two for social media…"), beep-then-speak cues, plain language,
and error-tolerant retries — per the OZCHI '25 voice-onboarding study and
the A11yExtensions co-design guidance for older adults.

Flow: the HOST voice speaks each question (/api/setup/host), the learner
answers by voice, /api/setup/voice transcribes + maps the answer to a
choice (subject → depth → style), and the wizard starts the debate.
"""
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..config import get_settings
from ..prompts import load_scenarios
from ..services import llm, stt, tts
from .chat import _validate_language

router = APIRouter(prefix="/setup", tags=["setup"])

DEPTH_LABELS = {"beginner": "Basics", "intermediate": "Balanced", "fluent": "Expert"}
STYLE_LABELS = {
    "devils_advocate": "Devil's advocate",
    "socratic": "Socratic",
    "heckler": "Heckler",
    "boardroom": "Boardroom",
    "encouraging": "Encouraging",
}


def _subject_options() -> list[dict]:
    return [{"id": s["id"], "label": s["title"]} for s in load_scenarios()]


def _match_key_or_number(raw: str, choices: list[tuple[str, str]]) -> dict:
    """One generic mapper: the LLM's answer matches a choice key or the
    1-based ordinal it was read aloud as. Ordinals are explicit DATA — the
    insertion order of the choices list, never a dict's."""
    by_key = {key: label for key, label in choices}
    if raw in by_key:
        return {"unclear": False, "choice": raw, "label": by_key[raw]}
    if raw.isdigit() and 1 <= int(raw) <= len(choices):
        key, label = choices[int(raw) - 1]
        return {"unclear": False, "choice": key, "label": label}
    return {"unclear": True, "choice": None, "label": None}


async def _map_answer(step: str, transcript: str) -> dict:
    """Map a spoken answer to a choice with the cheap LLM call. Returns
    {unclear: bool, choice: str|None, label: str|None}."""
    opts = _subject_options()  # one build per answer (lru-cached YAML read)
    if step == "subject":
        choices = [(o["id"], o["label"]) for o in opts]
        listing = "; ".join(f"{i+1} = {label}" for i, (_, label) in enumerate(choices))
        system = (
            "You map a spoken answer to a debate subject. The learner said a "
            f"number, a subject name, or 'free'. Options: {listing}; also "
            "'free' means free debate. Reply with ONLY the option id — "
            "'free' when they want to pick their own topic. Reply 'unclear' "
            "when nothing matches."
        )
        result = _match_key_or_number((await _fast_answer(system, transcript)), choices)
        if not result["unclear"]:
            return result
        return _match_key_or_number("free", [("free", "Free debate")])             if (await _fast_answer(system, transcript)).lower() == "free"             else result
    if step == "depth":
        choices = [(lvl, DEPTH_LABELS[lvl]) for lvl in ("beginner", "intermediate", "fluent")]
    else:  # style
        choices = list(STYLE_LABELS.items())
    listing = "; ".join(f"{i+1} = {label}" for i, (_, label) in enumerate(choices))
    system = (
        "You map a spoken answer. Reply with ONLY the choice key. "
        f"Options: {listing}. Reply 'unclear' when nothing matches."
    )
    return _match_key_or_number((await _fast_answer(system, transcript)), choices)


async def _fast_answer(system: str, transcript: str) -> str:
    raw = await llm.chat_reply_fast([
        {"role": "system", "content": system},
        {"role": "user", "content": f"The learner said: \"{transcript}\""},
    ])
    return (raw or "").strip().lower()


@router.post("/voice")
async def voice_setup_parse(
    step: str = Form(...),
    language: str = Form("en"),
    audio: UploadFile = File(...),
):
    """One spoken answer → a mapped choice for the wizard step."""
    if step not in ("subject", "depth", "style"):
        raise HTTPException(422, "step must be subject|depth|style")
    _validate_language(language)
    audio_bytes = await audio.read()
    if len(audio_bytes) > get_settings().max_audio_bytes:
        raise HTTPException(413, "Audio too large")
    transcript = await stt.transcribe(audio_bytes, language)
    if not transcript:
        return {"transcript": "", "unclear": True, "choice": None, "label": None}
    mapped = await _map_answer(step, transcript)
    return {"transcript": transcript, **mapped}


@router.post("/host")
async def host_tts(text: str = Form(...), language: str = Form("en")):
    """A host-voice line for the wizard (moderator voice, spoken prompts)."""
    audio = await tts.synthesize(text, language, tts.moderator_voice(language))
    return {"audio_base64": audio}
