"""Realtime voice quota accounting — the usage_audio table.

v11 M1 (2026-08-08): the realtime bridge meters seconds of audio (input +
output) per day. Registered users are keyed by user_id (ip ''), guests by
client IP (user_id NULL). Checked at WS accept by the realtime router and
incremented by the bridge as audio flows.

Writes are UPDATE-first with an INSERT fallback: SQLite treats NULLs as
distinct in unique keys, so `ON CONFLICT` upserts would never fire for
guest rows (user_id NULL). The shared single connection serializes calls,
so the check-then-insert cannot race.
"""
from datetime import datetime, timezone

from .database import get_db


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


async def seconds_used_today(user_id: str = "", ip: str = "", day: str | None = None) -> int:
    """Seconds of realtime audio already consumed today (UTC)."""
    day = day or _today()
    db = get_db()
    if user_id:
        async with db.execute(
            "SELECT COALESCE(SUM(seconds), 0) AS s FROM usage_audio "
            "WHERE user_id = ? AND day = ?",
            (user_id, day),
        ) as cur:
            row = await cur.fetchone()
    else:
        async with db.execute(
            "SELECT COALESCE(SUM(seconds), 0) AS s FROM usage_audio "
            "WHERE user_id IS NULL AND ip = ? AND day = ?",
            (ip, day),
        ) as cur:
            row = await cur.fetchone()
    return int(row["s"]) if row else 0


async def add_seconds(user_id: str = "", ip: str = "", seconds: int = 0,
                      day: str | None = None) -> None:
    """Add consumed audio seconds to today's counter. Sub-second remainders
    are the caller's problem (the bridge flushes whole seconds only)."""
    seconds = int(seconds)
    if seconds <= 0:
        return
    day = day or _today()
    db = get_db()
    if user_id:
        cur = await db.execute(
            "UPDATE usage_audio SET seconds = seconds + ? "
            "WHERE user_id = ? AND ip = '' AND day = ?",
            (seconds, user_id, day),
        )
    else:
        cur = await db.execute(
            "UPDATE usage_audio SET seconds = seconds + ? "
            "WHERE user_id IS NULL AND ip = ? AND day = ?",
            (seconds, ip, day),
        )
    if cur.rowcount == 0:
        await db.execute(
            "INSERT INTO usage_audio (user_id, ip, day, seconds) VALUES (?, ?, ?, ?)",
            (user_id or None, "" if user_id else ip, day, seconds),
        )
    await db.commit()
