"""Long-term user memory (v13.1) — "a friend you meet every time".

Tiers (research-informed, 2026-08-19): episodic (LLM-crystallized session
summaries, auto-injected at the next session start) + semantic (durable
facts/preferences/patterns). The memory is consolidated by an LLM pass at
session end (newer facts supersede older ones), bounded in size, scoped
per user, and injected into every system prompt.
"""
import json
from datetime import datetime, timezone

from .database import get_db

DEFAULT_MEMORY = {
    "about": {},       # semantic: durable facts/preferences the user stated
    "episodes": [],    # episodic: rolling session summaries (most recent last)
    "patterns": [],    # recurring behaviors: fallacies leaned on, delivery
    "threads": [],     # open topics: {topic, last_position, last_date}
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def load_memory(user_id: str) -> dict:
    """The user's memory JSON (deep-copied default when none exists)."""
    db = get_db()
    async with db.execute(
        "SELECT memory_json FROM user_memories WHERE user_id = ?", (user_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return json.loads(json.dumps(DEFAULT_MEMORY))
    try:
        mem = json.loads(row["memory_json"])
        if isinstance(mem, dict):
            return mem
    except json.JSONDecodeError:
        pass
    return json.loads(json.dumps(DEFAULT_MEMORY))


async def save_memory(user_id: str, memory: dict) -> None:
    db = get_db()
    await db.execute(
        """
        INSERT INTO user_memories (user_id, memory_json, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET memory_json = excluded.memory_json,
                                           updated_at = excluded.updated_at
        """,
        (user_id, json.dumps(memory, ensure_ascii=False), _now()),
    )
    await db.commit()


async def delete_memory(user_id: str) -> None:
    db = get_db()
    await db.execute("DELETE FROM user_memories WHERE user_id = ?", (user_id,))
    await db.commit()
