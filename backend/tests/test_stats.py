"""Stats honesty (v10, 2026-08-06): streaks count consecutive days with ≥1
USER message (a bare session row no longer counts); total_minutes clamps
each session to ≤60 min and ignores sessions without user messages."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from app.db import stats_store
from app.db.database import get_db


def _run(coro):
    return asyncio.run(coro)


def _uid() -> str:
    return f"stats_{uuid.uuid4().hex[:12]}"


def _iso(dt: datetime) -> str:
    return dt.isoformat()


async def _insert_session(user_id: str, started_at: datetime, last_active: datetime) -> str:
    sid = uuid.uuid4().hex
    db = get_db()
    await db.execute(
        "INSERT INTO sessions (id, user_id, language, native_language, level, started_at, last_active)"
        " VALUES (?, ?, 'fr', 'en', 'beginner', ?, ?)",
        (sid, user_id, _iso(started_at), _iso(last_active)),
    )
    await db.commit()
    return sid


async def _insert_user_message(session_id: str, created_at: datetime) -> None:
    db = get_db()
    await db.execute(
        "INSERT INTO messages (session_id, seq, role, text, created_at) VALUES (?, 1, 'user', 'hi', ?)",
        (session_id, _iso(created_at)),
    )
    await db.commit()


def test_streak_counts_user_message_days_not_session_rows(client):
    """Sessions alone must not build a streak — only days the user actually
    sent a message count (old code counted bare session rows)."""
    user = _uid()
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)

    # Session rows today + yesterday, zero messages → no streak at all.
    _run(_insert_session(user, now, now))
    _run(_insert_session(user, yesterday, yesterday))
    assert _run(stats_store._streak_days(user)) == 0

    # User messages today + yesterday → streak 2.
    s_today = _run(_insert_session(user, now, now))
    _run(_insert_user_message(s_today, now))
    s_yday = _run(_insert_session(user, yesterday, yesterday))
    _run(_insert_user_message(s_yday, yesterday))
    assert _run(stats_store._streak_days(user)) == 2

    # A 0-message session two days ago must NOT extend the streak.
    two_days_ago = now - timedelta(days=2)
    _run(_insert_session(user, two_days_ago, two_days_ago))
    assert _run(stats_store._streak_days(user)) == 2

    # …but a user message that day does.
    s2 = _run(_insert_session(user, two_days_ago, two_days_ago))
    _run(_insert_user_message(s2, two_days_ago))
    assert _run(stats_store._streak_days(user)) == 3


def test_total_minutes_clamped_and_requires_user_message(client):
    """Per-session contribution is capped at 60 min, and sessions without a
    user message contribute nothing (idle open tabs don't bank time)."""
    user = _uid()
    now = datetime.now(timezone.utc)

    # 90-minute session WITH a user message → clamped to 60.
    s1 = _run(_insert_session(user, now - timedelta(minutes=90), now))
    _run(_insert_user_message(s1, now - timedelta(minutes=80)))
    # 30-minute session WITHOUT any user message → counts 0.
    _run(_insert_session(user, now - timedelta(minutes=30), now))
    # 20-minute session with a user message → full 20.
    s3 = _run(_insert_session(user, now - timedelta(minutes=20), now))
    _run(_insert_user_message(s3, now - timedelta(minutes=15)))

    stats = _run(stats_store.get_stats(user))
    assert stats["total_minutes"] == 80  # 60 (clamped) + 0 + 20
