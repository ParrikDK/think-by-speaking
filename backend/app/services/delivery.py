"""Delivery analytics — the "how you sound" pillar (Think By Speaking, v13.1).

Filler words are counted server-side with a cheap regex (no LLM call, the
card renders instantly); pace (words/sec) and pitch label (monotone vs
varied) are computed from the client-measured audio duration and pitch
variance (cascade form fields / realtime turn_metrics frame). One shared
attach_metrics() owns the thresholds — the cascade routers and the
realtime bridge call the same code.
"""
import re

# Pace is reported when the turn has at least this many seconds of audio.
_MIN_AUDIO_SECS = 0.5
# Pitch variance below this (Hz stddev) reads as monotone delivery.
_MONOTONE_PITCH_VAR = 25.0

_FILLER_RE = re.compile(
    r"\b(um|uh|er|erm|like|you know|actually|basically|kind of|sort of|i mean)\b",
    re.IGNORECASE,
)


def count_fillers(text: str) -> int:
    """Number of spoken hesitation markers in the transcript."""
    if not text:
        return 0
    return len(_FILLER_RE.findall(text))


def attach_metrics(card: dict, user_text: str, audio_secs: float | None, pitch_var: float | None) -> None:
    """Attach the audio pillars to a feedback card (mutates in place):
    pace = words/sec from the client-measured duration; pitch label from
    the client-computed pitch variance. Conservative thresholds — never
    claim more than the metrics support."""
    if not card:
        return
    d: dict = {}
    if audio_secs and audio_secs > _MIN_AUDIO_SECS:
        d["pace"] = round(len(user_text.split()) / audio_secs, 1)
    if pitch_var is not None and pitch_var > 0:
        d["pitch"] = "monotone" if pitch_var < _MONOTONE_PITCH_VAR else "varied"
    if d:
        card["delivery"] = d
