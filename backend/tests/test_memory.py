"""Long-term memory tests (v13.1) — the 'friend you keep meeting' tier."""
import pytest

from app.db import memory_store


def _register(client, username):
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201)
    return r.json()["user"]["id"]


def test_memory_roundtrip(client):
    import asyncio

    async def _run():
        uid = _register(client, "memuser1")
        await memory_store.save_memory(uid, {
            "about": {"loves": "boba"},
            "episodes": [{"topic": "AI jobs", "note": "argued teachers are safe"}],
        })
        loaded = await memory_store.load_memory(uid)
        assert loaded["about"]["loves"] == "boba"
        assert loaded["episodes"][0]["topic"] == "AI jobs"

    asyncio.run(_run())


def test_memory_default_shape(client):
    async def _run():
        mem = await memory_store.load_memory("nobody-here")
        assert set(mem.keys()) == {"about", "episodes", "patterns", "threads"}
        assert mem["episodes"] == []

    import asyncio
    asyncio.run(_run())


def test_memory_delete(client):
    import asyncio

    async def _run():
        uid = _register(client, "memdeluser")
        await memory_store.save_memory(uid, {"about": {"x": 1}})
        await memory_store.delete_memory(uid)
        mem = await memory_store.load_memory(uid)
        assert mem["about"] == {}

    asyncio.run(_run())


def test_memory_injected_for_logged_in_users(client, monkeypatch):
    """The REMEMBERED block reaches the system prompt for accounts."""
    from app.db import memory_store

    captured = []

    async def fake_chat_json(messages, language="en", native_language="en"):
        captured.append(messages)
        return {"reply": "Hello again!", "translation": "", "feedback": None}

    async def fake_synthesize(text, language="en", voice_id=None, level="beginner", **kw):
        return "QUJD"

    monkeypatch.setattr("app.services.llm.chat_json", fake_chat_json)
    monkeypatch.setattr("app.services.tts.synthesize", fake_synthesize)

    async def _seed_and_init():
        uid = _register(client, "memuser2")
        await memory_store.save_memory(uid, {
            "episodes": [{"topic": "remote work", "note": "you steelmanned well"}],
        })
        r = client.post(
            "/api/chat/init",
            data={"language": "en", "native_language": "en", "level": "intermediate"},
            headers={"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'memuser2', 'password': 'pw123456'}).json()['token']}"},
        )
        assert r.status_code == 200, r.text

    import asyncio
    asyncio.run(_seed_and_init())
    assert captured, "chat_json was never called"
    system = captured[0][0]["content"]
    assert "REMEMBERED" in system
    assert "steelmanned well" in system
    assert "NATURAL CONVERSATION" in system


def test_summary_consolidates_memory(client, monkeypatch):
    """Ending a session as a logged-in user consolidates the memory
    (the 500-regression guard from the QA battery)."""
    from app.db import memory_store

    async def fake_fast(messages):
        # summary recap on the first call, memory merge on the second
        if "maintain a learner" in (messages[0].get("content") or ""):
            return '{"about": {"goal": "learn by debating"}, "episodes": [], "patterns": [], "threads": []}'
        return "You finished at 54. Good debate."

    async def fake_chat_json(messages, language="en", native_language="en"):
        return {"reply": "Greeting!", "translation": "", "feedback": None}

    async def fake_synthesize(text, language="en", voice_id=None, level="beginner", **kw):
        return "QUJD"

    monkeypatch.setattr("app.services.llm.chat_reply_fast", fake_fast)
    monkeypatch.setattr("app.services.llm.chat_json", fake_chat_json)
    monkeypatch.setattr("app.services.tts.synthesize", fake_synthesize)

    import asyncio

    async def _run():
        uid = _register(client, "qamemuser")
        r = client.post(
            "/api/chat/init",
            data={"language": "en", "native_language": "en", "level": "intermediate"},
            headers={"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'qamemuser', 'password': 'pw123456'}).json()['token']}"},
        )
        sid = r.json()["session_id"]
        r = client.post("/api/chat", data={"session_id": sid, "language": "en", "text": "claim"}, headers={"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'qamemuser', 'password': 'pw123456'}).json()['token']}"})
        assert r.status_code == 200
        r = client.post("/api/chat/summary", data={"session_id": sid, "language": "en"}, headers={"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': 'qamemuser', 'password': 'pw123456'}).json()['token']}"})
        assert r.status_code == 200, r.text  # THE regression: was a 500
        await asyncio.sleep(0.3)  # let the background consolidation land
        mem = await memory_store.load_memory(uid)
        assert mem["about"].get("goal") == "learn by debating"

    asyncio.run(_run())
