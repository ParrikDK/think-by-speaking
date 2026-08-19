"""Single shared aiosqlite connection (WAL mode) + schema.

Tables: sessions, messages, users, tokens, user_stats, usage_audio.

v11 M1 (2026-08-08): usage_audio — realtime voice quota accounting
(seconds of audio per user/day, guests keyed by IP).
"""
from typing import Optional

import aiosqlite
from loguru import logger

from ..config import get_settings

_db: Optional[aiosqlite.Connection] = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT,                -- NULL for guest sessions
    language TEXT NOT NULL,
    native_language TEXT NOT NULL DEFAULT 'en',
    level TEXT NOT NULL,
    scenario_id TEXT,
    voice_id TEXT,
    profile_json TEXT,           -- v13: learner profile {interests, style} for personalization
    started_at TEXT NOT NULL,
    last_active TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, last_active);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    translation TEXT,
    pronunciation TEXT DEFAULT '',
    grammar_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, seq);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,  -- "<salt_hex>$<pbkdf2_hex>"
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tokens (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_tokens_user ON tokens(user_id);

CREATE TABLE IF NOT EXISTS user_stats (
    user_id TEXT PRIMARY KEY,
    total_sessions INTEGER NOT NULL DEFAULT 0,
    total_messages INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- v13.1 (2026-08-19): long-term user memory — the "friend you meet every
-- time" tier. One rolling memory JSON per user (episodic + semantic),
-- consolidated by an LLM pass at session end, injected every turn.
CREATE TABLE IF NOT EXISTS user_memories (
    user_id TEXT PRIMARY KEY,
    memory_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- v11 M1 (2026-08-08): realtime voice quota. Guests: user_id NULL, keyed
-- by ip; registered users: keyed by user_id (ip ''). One row per key/day.
CREATE TABLE IF NOT EXISTS usage_audio (
    user_id TEXT,
    ip TEXT NOT NULL DEFAULT '',
    day TEXT NOT NULL,           -- UTC date, YYYY-MM-DD
    seconds INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, ip, day)
);
"""


async def init_db(db_path: str | None = None) -> aiosqlite.Connection:
    """Open the shared connection and create the schema. Idempotent."""
    global _db
    if _db is not None:
        return _db
    path = db_path or get_settings().database_path
    _db = await aiosqlite.connect(path)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    await _db.execute("PRAGMA busy_timeout=5000")
    await _db.executescript(SCHEMA)
    try:
        await _db.execute("ALTER TABLE messages ADD COLUMN pronunciation TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        await _db.execute("ALTER TABLE sessions ADD COLUMN profile_json TEXT")
    except Exception:
        pass
    await _db.commit()
    logger.info("Database initialised at {}", path)
    return _db


def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not initialised — call init_db() first")
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None
