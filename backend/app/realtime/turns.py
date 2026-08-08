"""Realtime turn accounting + persistence.

v11 M1 (2026-08-08). Tracks one realtime connection's turns (user
transcript → tutor reply → response.done) exactly like the spike did, and
persists each completed, non-cancelled turn into the same `messages` table
the cascade chat uses — through the session_store.commit_turn choke point —
so History and Progress work for realtime sessions unchanged.

Deliberate simplifications (documented in the v11 plan):
- Grammar cards are NOT persisted. They resolve asynchronously after the
  turn lands and the messages schema has no update path; they stay a
  live-session aid.
- Wrong-script ASR misfires are persisted with their raw transcript (the
  UI blanks them live, but the row is the faithful record of what the
  tutor actually replied to).
- A turn whose response was cancelled (barge-in) is not persisted — the
  conversation visibly continued, so there is no completed exchange to log.
"""
from dataclasses import dataclass

from loguru import logger

from ..db import stats_store
from ..db.session_store import SessionData, session_store
from ..db.user_store import User
from ..services.romanize import romanize


async def create_session(
    lang: str,
    level: str,
    native_language: str,
    scenario_id: str | None,
    voice_id: str,
    user: User | None,
) -> SessionData:
    """Register the realtime session like a cascade session: in-memory via
    session_store (flushed to SQLite by the write-behind loop), plus the
    per-user session counter for Progress."""
    session = session_store.create(
        SessionData(
            language=lang,
            native_language=native_language,
            level=level,
            scenario_id=scenario_id,
            voice_id=voice_id,
            user_id=user.id if user else "",
        )
    )
    if user:
        await stats_store.record_session_created(user.id)
    return session


@dataclass
class TurnRecord:
    """One user utterance and the tutor's reply to it."""

    user: str
    tutor: str = ""
    response_done: bool = False
    persisted: bool = False
    grammar_sent: bool = False


class TurnTracker:
    """Per-connection turn numbering + completion + persistence.

    Mirrors the spike's state machine: `turn` counts completed user
    utterances (ASR transcripts and typed text alike); a rare
    response.done that lands before its transcript attaches to the NEXT
    transcript (`done_before_transcript`).
    """

    def __init__(self, session: SessionData):
        self.session = session
        self.turn = 0
        self.records: dict[int, TurnRecord] = {}
        self.done_before_transcript = False

    def note_user_transcript(self, text: str) -> int:
        """Register a completed user utterance; returns its turn number."""
        self.turn += 1
        self.records[self.turn] = TurnRecord(
            user=text,
            response_done=self.done_before_transcript,
        )
        self.done_before_transcript = False
        return self.turn

    def note_tutor_text(self, text: str) -> None:
        """Attach the tutor's finished reply text to the current turn."""
        rec = self.records.get(self.turn)
        if rec is not None:
            rec.tutor = text

    def note_response_done(self, cancelled: bool) -> None:
        """Mark the current turn's response finished (unless cancelled)."""
        if cancelled:
            return
        rec = self.records.get(self.turn)
        if rec is not None:
            rec.response_done = True
        else:
            # This turn's user transcript has not landed yet; attach the
            # done to the next transcript that does.
            self.done_before_transcript = True

    def completed(self, turn: int) -> TurnRecord | None:
        """The turn's record once both halves exist (utterance + finished
        response), exactly once."""
        rec = self.records.get(turn)
        if not rec or rec.persisted or not rec.user or not rec.response_done:
            return None
        return rec

    async def persist_turn(self, turn: int) -> bool:
        """Write a completed turn into the messages table via the
        session_store choke point (user + assistant rows, with
        romanization in the pronunciation column for CJK sessions)."""
        rec = self.completed(turn)
        if rec is None:
            return False
        rec.persisted = True
        lang = self.session.language
        try:
            session_store.commit_turn(
                self.session,
                rec.user,
                {
                    "text": rec.tutor,
                    "translation": None,
                    "pronunciation": romanize(rec.tutor, lang) or "",
                    "grammar": None,
                },
                user_pronunciation=romanize(rec.user, lang) or "",
            )
        except Exception as exc:
            # Persistence must never break the voice path.
            logger.error("Realtime turn {} persistence failed: {}", turn, exc)
            return False
        if self.session.user_id:
            for _ in range(2):  # user + assistant message
                await stats_store.record_message(self.session.user_id)
        # Eager flush: ASGI servers may cancel the WS handler task the
        # moment the client disconnects (starlette's TestClient always
        # does), so waiting for connection teardown to persist is not
        # reliable — the turn is written through as soon as it completes.
        # Failure is logged, never fatal to the voice path.
        try:
            await session_store.flush_session(self.session)
        except Exception as exc:
            logger.error("Realtime turn {} flush failed: {}", turn, exc)
        return True
