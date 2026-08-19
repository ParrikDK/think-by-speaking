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
from ..prompts.tutor import VALID_LEVELS
from ..services import llm, stt, tts

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


async def _map_answer(step: str, transcript: str) -> dict:
    """Map a spoken answer to a choice with the cheap LLM call. Returns
    {unclear: bool, choice: str|None, label: str|None}."""
    if step == "subject":
        opts = _subject_options()
        listing = "; ".join(f"{i+1} = {o['label']}" for i, o in enumerate(opts))
        valid = [o["id"] for o in opts] + ["free"]
        system = (
            "You map a spoken answer to a debate subject. The learner said a "
            f"number, a subject name, or 'free'. Options: {listing}; also "
            "'free' means free debate. Reply with ONLY the option id — "
            "'free' when they want to pick their own topic. Reply 'unclear' "
            "when nothing matches."
        )
    elif step == "depth":
        system = (
            "You map a spoken answer to a debate depth: Basics, Balanced or "
            "Expert. Reply with ONLY beginner, intermediate or fluent. "
            "Reply 'unclear' when nothing matches."
        )
    else:  # style
        listing = "; ".join(f"{i+1} = {v}" for i, v in enumerate(STYLE_LABELS.values()))
        system = (
            f"You map a spoken answer to a coaching style: {listing}. "
            "Reply with ONLY the style key (devils_advocate, socratic, "
            "heckler, boardroom or encouraging). Reply 'unclear' when "
            "nothing matches."
        )

    raw = await llm.chat_reply_fast([
        {"role": "system", "content": system},
        {"role": "user", "content": f"The learner said: \"{transcript}\""},
    ])
    raw = (raw or "").strip().lower()
    if not raw or raw == "unclear":
        return {"unclear": True, "choice": None, "label": None}

    if step == "subject":
        by_id = {o["id"]: o["label"] for o in _subject_options()}
        # accept the spoken id, or the 1-based number they were read
        if raw in by_id:
            return {"unclear": False, "choice": raw, "label": by_id[raw]}
        if raw.isdigit() and 1 <= int(raw) <= len(by_id):
            o = _subject_options()[int(raw) - 1]
            return {"unclear": False, "choice": o["id"], "label": o["label"]}
        if raw == "free":
            return {"unclear": False, "choice": "free", "label": "Free debate"}
        return {"unclear": True, "choice": None, "label": None}

    if step == "depth":
        if raw in VALID_LEVELS:
            return {"unclear": False, "choice": raw, "label": DEPTH_LABELS[raw]}
        # number mapping: 1 = Basics, 2 = Balanced, 3 = Expert
        if raw.isdigit() and 1 <= int(raw) <= 3:
            lvl = VALID_LEVELS[int(raw) - 1]
            return {"unclear": False, "choice": lvl, "label": DEPTH_LABELS[lvl]}
        return {"unclear": True, "choice": None, "label": None}

    if raw in STYLE_LABELS:
        return {"unclear": False, "choice": raw, "label": STYLE_LABELS[raw]}
    if raw.isdigit() and 1 <= int(raw) <= len(STYLE_LABELS):
        key = list(STYLE_LABELS)[int(raw) - 1]
        return {"unclear": False, "choice": key, "label": STYLE_LABELS[key]}
    return {"unclear": True, "choice": None, "label": None}


@router.post("/voice")
async def voice_setup_parse(
    step: str = Form(...),
    language: str = Form("en"),
    audio: UploadFile = File(...),
):
    """One spoken answer → a mapped choice for the wizard step."""
    if step not in ("subject", "depth", "style"):
        raise HTTPException(422, "step must be subject|depth|style")
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
