"""Session store — in-memory cache + SQLite write-behind.

- Guest sessions (no user_id): live in memory with a 30-minute TTL, are
  flushed to SQLite by a background write-behind task (and on shutdown),
  and are re-loadable from SQLite after a cache miss or restart — so a
  server restart does NOT kill an active guest session (within its TTL).
- Authenticated sessions: same in-memory cache, but they never expire and
  are re-loadable from SQLite after a cache miss or restart.
"""
import asyncio
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

from ..config import get_settings
from .database import get_db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class SessionData:
    language: str
    native_language: str = "en"
    level: str = "beginner"
    scenario_id: Optional[str] = None
    voice_id: str = ""
    user_id: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: datetime = field(default_factory=_now)
    last_active: datetime = field(default_factory=_now)
    messages: list[dict] = field(default_factory=list)
    persisted_messages: int = 0  # how many messages are already in SQLite
    dirty: bool = True
    profile: Optional[dict] = None  # v13: learner interests/style for personalization

    @property
    def is_guest(self) -> bool:
        return not self.user_id

    def touch(self) -> None:
        self.last_active = _now()
        self.dirty = True

    def add_message(
        self,
        role: str,
        text: str,
        translation: str | None = None,
        pronunciation: str = "",
        grammar: dict | None = None,
    ) -> None:
        self.messages.append(
            {
                "role": role,
                "text": text,
                "translation": translation,
                "pronunciation": pronunciation,
                "grammar": grammar,
                "created_at": _iso(_now()),
            }
        )
        self.touch()


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionData] = {}
        self._flush_task: Optional[asyncio.Task] = None
        self._locks: dict[str, asyncio.Lock] = {}

    def session_lock(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    # ── lifecycle ──

    def start(self) -> None:
        interval = get_settings().flush_interval_seconds

        async def _loop() -> None:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self.flush()
                except Exception as exc:
                    logger.error("Session flush failed: {}", exc)
                try:
                    await self._purge_expired()
                except Exception as exc:
                    logger.error("Session purge failed: {}", exc)

        self._flush_task = asyncio.create_task(_loop())

    async def shutdown(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        await self.flush()

    # ── CRUD ──

    def create(self, session: SessionData) -> SessionData:
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Optional[SessionData]:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.is_guest and self._expired(session):
            del self._sessions[session_id]
            return None
        return session

    async def get_or_load(self, session_id: str) -> Optional[SessionData]:
        """Memory first; any persisted session (guest or authenticated) falls
        back to SQLite after a restart. Expired guest sessions are discarded."""
        session = self.get(session_id)
        if session is not None:
            return session
        db = get_db()
        async with db.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        session = SessionData(
            id=row["id"],
            user_id=row["user_id"] or "",
            language=row["language"],
            native_language=row["native_language"],
            level=row["level"],
            scenario_id=row["scenario_id"],
            voice_id=row["voice_id"] or "",
            started_at=_parse(row["started_at"]),
            last_active=_parse(row["last_active"]),
            profile=(
                json.loads(row["profile_json"])
                if row["profile_json"] else None
            ),
        )
        async with db.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY seq", (session_id,)
        ) as cur:
            rows = await cur.fetchall()
        for r in rows:
            session.messages.append(
                {
                    "role": r["role"],
                    "text": r["text"],
                    "translation": r["translation"],
                    "pronunciation": r["pronunciation"] if "pronunciation" in r.keys() else "",
                    "grammar": json.loads(r["grammar_json"]) if r["grammar_json"] else None,
                    "created_at": r["created_at"],
                }
            )
        session.persisted_messages = len(rows)
        session.dirty = False
        if session.is_guest and self._expired(session):
            return None  # expired guest session — do not resurrect
        self._sessions[session.id] = session
        return session

    def evict(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._locks.pop(session_id, None)

    def sessions_for_user(self, user_id: str) -> list[SessionData]:
        return [s for s in self._sessions.values() if s.user_id == user_id]

    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if not (s.is_guest and self._expired(s)))

    def _expired(self, session: SessionData) -> bool:
        ttl = timedelta(minutes=get_settings().session_ttl_minutes)
        return _now() - session.last_active > ttl

    def commit_turn(self, session: SessionData, user_text: str, assistant: dict,
                    user_pronunciation: str = "") -> None:
        session.add_message("user", user_text, pronunciation=user_pronunciation)
        session.add_message(
            "assistant", assistant["text"], translation=assistant.get("translation"),
            pronunciation=assistant.get("pronunciation", ""),
            grammar=assistant.get("grammar"),
        )

    async def _purge_expired(self) -> None:
        """Delete expired guest sessions from memory and SQLite."""
        expired_ids = [
            sid for sid, s in self._sessions.items()
            if s.is_guest and self._expired(s)
        ]
        if not expired_ids:
            return
        for sid in expired_ids:
            self._sessions.pop(sid, None)
            self._locks.pop(sid, None)
        db = get_db()
        placeholders = ",".join("?" for _ in expired_ids)
        await db.execute(
            f"DELETE FROM messages WHERE session_id IN ({placeholders})",
            expired_ids,
        )
        await db.execute(
            f"DELETE FROM sessions WHERE id IN ({placeholders})",
            expired_ids,
        )
        await db.commit()
        logger.info("Purged {} expired guest sessions", len(expired_ids))

    # ── write-behind persistence ──

    async def flush(self) -> None:
        dirty = [s for s in self._sessions.values() if s.dirty]
        for session in dirty:
            try:
                await self._persist(session)
                session.dirty = False
            except Exception as exc:
                logger.error("Failed to persist session {}: {}", session.id, exc)

    async def flush_session(self, session: SessionData) -> None:
        if not session.dirty:
            return
        await self._persist(session)
        session.dirty = False

    async def _persist(self, session: SessionData) -> None:
        # Serialized per session: the realtime module flushes eagerly at
        # turn completion (v11 M1), which can overlap the write-behind loop.
        async with self.session_lock(session.id):
            await self._persist_locked(session)

    async def _persist_locked(self, session: SessionData) -> None:
        db = get_db()
        await db.execute(
            """
            INSERT INTO sessions (id, user_id, language, native_language, level,
                                  scenario_id, voice_id, profile_json,
                                  started_at, last_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                user_id = excluded.user_id,
                voice_id = excluded.voice_id,
                profile_json = excluded.profile_json,
                last_active = excluded.last_active
            """,
            (
                session.id,
                session.user_id or None,
                session.language,
                session.native_language,
                session.level,
                session.scenario_id,
                session.voice_id,
                json.dumps(session.profile, ensure_ascii=False) if session.profile else None,
                _iso(session.started_at),
                _iso(session.last_active),
            ),
        )
        new_messages = session.messages[session.persisted_messages :]
        for i, msg in enumerate(new_messages):
            seq = session.persisted_messages + i
            await db.execute(
                """
                INSERT INTO messages (session_id, seq, role, text, translation,
                                      pronunciation, grammar_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    seq,
                    msg["role"],
                    msg["text"],
                    msg.get("translation"),
                    msg.get("pronunciation", ""),
                    json.dumps(msg["grammar"], ensure_ascii=False) if msg.get("grammar") else None,
                    msg["created_at"],
                ),
            )
        session.persisted_messages = len(session.messages)
        await db.commit()


session_store = SessionStore()
