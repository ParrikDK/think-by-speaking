"""Session store — guest sessions survive a 'restart' (cache clear) within
their TTL, so a server restart no longer kills active guest conversations."""
import asyncio
from datetime import timedelta

from app.db.database import get_db
from app.db.session_store import SessionData, _iso, _now, session_store


def _run(coro):
    return asyncio.run(coro)


def test_guest_session_survives_restart(client):
    """A persisted guest session is re-loadable after the in-memory cache
    is cleared — the exact scenario of a server restart."""
    session = session_store.create(SessionData(language="yue", level="beginner"))
    session.add_message("user", "hello")
    session.add_message("assistant", "你好！", translation="")
    _run(session_store.flush())

    session_store._sessions.clear()  # simulate restart: memory wiped

    loaded = _run(session_store.get_or_load(session.id))
    assert loaded is not None, "guest session should be re-loadable after restart"
    assert loaded.language == "yue"
    assert loaded.level == "beginner"
    assert [m["text"] for m in loaded.messages] == ["hello", "你好！"]
    assert loaded.persisted_messages == 2
    assert not loaded.dirty


def test_expired_guest_session_not_resurrected(client):
    """Sessions past their TTL are discarded on reload, not resurrected."""
    session = session_store.create(SessionData(language="fr"))
    session.add_message("user", "hi")
    _run(session_store.flush())

    async def backdate():
        db = get_db()
        await db.execute(
            "UPDATE sessions SET last_active = ? WHERE id = ?",
            (_iso(_now() - timedelta(minutes=999)), session.id),
        )
        await db.commit()

    _run(backdate())
    session_store._sessions.clear()

    loaded = _run(session_store.get_or_load(session.id))
    assert loaded is None, "expired guest sessions must not be resurrected"
