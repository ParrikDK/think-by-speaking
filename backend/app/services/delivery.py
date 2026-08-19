"""Delivery analytics — the "how you sound" pillar (RhetoricX, v13.1).

Current: filler-word counting on the learner's SPOKEN transcript (typed
input carries no delivery signal). Planned: pitch variance and speaking
rate from the recorded audio (see frontend audio analysis + turn_metrics).

Fillers are counted server-side with a cheap regex — no LLM call — so the
card renders instantly with the reply.
"""
import re

_FILLER_RE = re.compile(
    r"\b(um|uh|er|erm|like|you know|actually|basically|kind of|sort of|i mean)\b",
    re.IGNORECASE,
)


def count_fillers(text: str) -> int:
    """Number of spoken hesitation markers in the transcript."""
    if not text:
        return 0
    return len(_FILLER_RE.findall(text))
