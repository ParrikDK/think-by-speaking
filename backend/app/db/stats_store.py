"""Stats + history queries for authenticated users.

- total_sessions / total_messages: counters in user_stats (kept in sync by
  record_session_created / record_message / delete_session).
- total_minutes: actually computed from session durations
  (last_active - started_at) — not a static counter. v10 (2026-08-06):
  per-session contribution is clamped to ≤60 min and sessions without a
  single user message count nothing (idle open tabs no longer inflate it).
- by_language / recent_sessions: derived from sessions+messages.
- streak_days: v10 — consecutive days with ≥1 USER message (a bare
  0-message session row no longer extends the streak).
"""
from datetime import datetime, timezone
from typing import Optional

from .database import get_db


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def record_session_created(user_id: str) -> None:
    db = get_db()
    await db.execute(
        """
        INSERT INTO user_stats (user_id, total_sessions, total_messages) VALUES (?, 1, 0)
        ON CONFLICT(user_id) DO UPDATE SET total_sessions = total_sessions + 1
        """,
        (user_id,),
    )
    await db.commit()


async def record_message(user_id: str) -> None:
    db = get_db()
    await db.execute(
        """
        INSERT INTO user_stats (user_id, total_sessions, total_messages) VALUES (?, 0, 1)
        ON CONFLICT(user_id) DO UPDATE SET total_messages = total_messages + 1
        """,
        (user_id,),
    )
    await db.commit()


async def list_sessions(user_id: str) -> list[dict]:
    """History list, most recent first, with live message counts."""
    db = get_db()
    async with db.execute(
        """
        SELECT s.id, s.language, s.level, s.scenario_id, s.started_at, s.last_active,
               COUNT(m.id) AS message_count
        FROM sessions s
        LEFT JOIN messages m ON m.session_id = s.id
        WHERE s.user_id = ?
        GROUP BY s.id
        ORDER BY s.last_active DESC
        """,
        (user_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [
        {
            "session_id": r["id"],
            "language": r["language"],
            "level": r["level"],
            "scenario_id": r["scenario_id"],
            "started_at": r["started_at"],
            "last_active": r["last_active"],
            "message_count": r["message_count"],
        }
        for r in rows
    ]


async def get_session_detail(user_id: str, session_id: str) -> Optional[dict]:
    db = get_db()
    async with db.execute(
        "SELECT * FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    import json

    async with db.execute(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY seq", (session_id,)
    ) as cur:
        msgs = await cur.fetchall()
    return {
        "session": {
            "session_id": row["id"],
            "language": row["language"],
            "level": row["level"],
            "scenario_id": row["scenario_id"],
            "started_at": row["started_at"],
            "last_active": row["last_active"],
            "message_count": len(msgs),
        },
        "messages": [
            {
                "role": m["role"],
                "text": m["text"],
                "translation": m["translation"],
                "grammar": json.loads(m["grammar_json"]) if m["grammar_json"] else None,
                "created_at": m["created_at"],
            }
            for m in msgs
        ],
    }


async def delete_session(user_id: str, session_id: str) -> bool:
    """Delete a user's session + messages; keeps user_stats counters in sync."""
    db = get_db()
    async with db.execute(
        "SELECT user_id FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id)
    ) as cur:
        if await cur.fetchone() is None:
            return False
    async with db.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE session_id = ?", (session_id,)
    ) as cur:
        n_messages = (await cur.fetchone())["n"]
    await db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    await db.execute(
        """
        UPDATE user_stats
        SET total_sessions = MAX(0, total_sessions - 1),
            total_messages = MAX(0, total_messages - ?)
        WHERE user_id = ?
        """,
        (n_messages, user_id),
    )
    await db.commit()
    return True


async def _total_minutes(user_id: str) -> int:
    """Sum of session durations (last_active - started_at), in minutes.

    v10 (2026-08-06) honesty clamps: a session counts only when it has ≥1
    user message, and each session contributes at most 60 minutes — an idle
    open tab used to bank hours of unearned practice time.
    """
    db = get_db()
    async with db.execute(
        """
        SELECT s.started_at, s.last_active,
               (SELECT COUNT(*) FROM messages m
                WHERE m.session_id = s.id AND m.role = 'user') AS user_msgs
        FROM sessions s
        WHERE s.user_id = ?
        """,
        (user_id,),
    ) as cur:
        rows = await cur.fetchall()
    total_seconds = 0.0
    for r in rows:
        if not r["user_msgs"]:
            continue
        try:
            delta = (_parse(r["last_active"]) - _parse(r["started_at"])).total_seconds()
            total_seconds += min(3600.0, max(0.0, delta))
        except (TypeError, ValueError):
            continue
    return round(total_seconds / 60)


async def _by_language(user_id: str) -> dict:
    db = get_db()
    async with db.execute(
        """
        SELECT s.language AS code,
               COUNT(DISTINCT s.id) AS sessions,
               COUNT(m.id) AS messages
        FROM sessions s
        LEFT JOIN messages m ON m.session_id = s.id
        WHERE s.user_id = ?
        GROUP BY s.language
        """,
        (user_id,),
    ) as cur:
        rows = await cur.fetchall()
    return {
        r["code"]: {"sessions": r["sessions"], "messages": r["messages"]} for r in rows
    }


async def _streak_days(user_id: str) -> int:
    """Consecutive days with ≥1 USER message, ending today or yesterday.

    v10 (2026-08-06): was "days with a sessions row" — opening a session
    without saying anything extended the streak. Real practice means a
    user message, so count distinct user-message days instead.
    """
    db = get_db()
    async with db.execute(
        """
        SELECT DISTINCT substr(m.created_at, 1, 10) AS day
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE s.user_id = ? AND m.role = 'user'
        """,
        (user_id,),
    ) as cur:
        rows = await cur.fetchall()
    days = {r["day"] for r in rows if r["day"]}
    if not days:
        return 0
    from datetime import timedelta

    today = datetime.now(timezone.utc).date()
    # Streak counts from today; if no activity today, start from yesterday.
    cursor = today if today.isoformat() in days else today - timedelta(days=1)
    if cursor.isoformat() not in days:
        return 0
    streak = 0
    while cursor.isoformat() in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


async def get_stats(user_id: str, include_recent: bool = False) -> dict:
    db = get_db()
    async with db.execute(
        "SELECT total_sessions, total_messages FROM user_stats WHERE user_id = ?",
        (user_id,),
    ) as cur:
        row = await cur.fetchone()
    stats = {
        "total_sessions": row["total_sessions"] if row else 0,
        "total_messages": row["total_messages"] if row else 0,
        "total_minutes": await _total_minutes(user_id),
        "by_language": await _by_language(user_id),
    }
    if include_recent:
        stats["streak_days"] = await _streak_days(user_id)
        stats["recent_sessions"] = (await list_sessions(user_id))[:5]
        stats["debate"] = await debate_trends(user_id)
    return stats


async def debate_trends(user_id: str, limit: int = 10) -> dict:
    """Think By Speaking memory (v13.1) — the moat: per-user debate analytics
    aggregated from the stored feedback cards. Progress persists across
    sessions: avg/best score, fallacy totals by type, filler totals, and a
    per-session score history for trend bars."""
    import json

    db = get_db()
    async with db.execute(
        """
        SELECT s.id AS session_id, s.started_at, m.grammar_json
        FROM messages m JOIN sessions s ON s.id = m.session_id
        WHERE s.user_id = ? AND m.role = 'assistant' AND m.grammar_json IS NOT NULL
        ORDER BY m.created_at
        """,
        (user_id,),
    ) as cur:
        rows = await cur.fetchall()

    per_session: dict[str, dict] = {}
    totals = {"turns": 0, "score_sum": 0, "best": 0, "fallacies": {}, "fillers": 0}
    for r in rows:
        try:
            card = json.loads(r["grammar_json"])
        except Exception:
            continue
        if not isinstance(card, dict) or "score" not in card:
            continue
        score = int(card.get("score") or 50)
        sid = r["session_id"]
        seg = per_session.setdefault(
            sid, {"started_at": r["started_at"], "score_sum": 0, "turns": 0, "scores": []}
        )
        seg["score_sum"] += score
        seg["turns"] += 1
        seg["scores"].append(score)
        totals["turns"] += 1
        totals["score_sum"] += score
        totals["best"] = max(totals["best"], score)
        totals["fillers"] += int(card.get("filler_count") or 0)
        for f in card.get("fallacies") or []:
            if isinstance(f, dict) and f.get("type"):
                totals["fallacies"][f["type"]] = totals["fallacies"].get(f["type"], 0) + 1

    history = [
        {
            "session_id": sid,
            "started_at": seg["started_at"],
            "turns": seg["turns"],
            "avg_score": round(seg["score_sum"] / seg["turns"]),
            "best": max(seg["scores"]),
        }
        for sid, seg in per_session.items()
    ]
    history.sort(key=lambda h: h["started_at"], reverse=True)
    return {
        "sessions": len(per_session),
        "turns": totals["turns"],
        "avg_score": round(totals["score_sum"] / totals["turns"]) if totals["turns"] else 0,
        "best_score": totals["best"],
        "fallacy_totals": totals["fallacies"],
        "filler_total": totals["fillers"],
        "score_history": history[:limit],
    }
