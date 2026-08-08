"""Auth flow via TestClient with a temp db: register → login → me → logout."""
import uuid
from datetime import datetime, timedelta, timezone


def _creds():
    return {"username": f"user_{uuid.uuid4().hex[:10]}", "password": "s3cret-pw"}


def test_register_login_me_logout_flow(client):
    creds = _creds()

    # register
    r = client.post("/api/auth/register", json=creds)
    assert r.status_code == 201, r.text
    body = r.json()
    token = body["token"]
    assert len(token) == 64  # 32-byte hex
    assert body["user"]["username"] == creds["username"]
    assert body["user"]["id"]

    # duplicate register → 409
    r = client.post("/api/auth/register", json=creds)
    assert r.status_code == 409

    # me with token
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    me = r.json()
    assert me["user"]["username"] == creds["username"]
    assert me["stats"]["total_sessions"] == 0
    assert me["stats"]["total_messages"] == 0
    assert me["stats"]["by_language"] == {}

    # bad login → 401
    r = client.post("/api/auth/login", json={**creds, "password": "wrong"})
    assert r.status_code == 401

    # good login
    r = client.post("/api/auth/login", json=creds)
    assert r.status_code == 200
    token2 = r.json()["token"]
    assert token2 != token

    # logout invalidates the token
    r = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token2}"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token2}"})
    assert r.status_code == 401


def test_me_requires_auth(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_stats_endpoint_shape(client):
    creds = _creds()
    token = client.post("/api/auth/register", json=creds).json()["token"]
    r = client.get("/api/stats", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    stats = r.json()
    for key in (
        "total_sessions", "total_messages", "total_minutes",
        "by_language", "streak_days", "recent_sessions",
    ):
        assert key in stats


def test_stats_counters_change_after_chat(client, monkeypatch):
    """Create an authenticated session and send a message —
    verify total_sessions and total_messages increment."""
    # Mock LLM and TTS so the chat endpoint works without real API calls
    FAKE_PAYLOAD = {
        "reply": "Bonjour ! Comment ça va ?",
        "translation": "Hello! How are you?",
        "grammar": None,
    }

    async def fake_chat_json(messages, language="en", native_language="en"):
        return dict(FAKE_PAYLOAD)

    async def fake_synthesize(*args, **kwargs):
        return "QUJD"

    monkeypatch.setattr("app.services.llm.chat_json", fake_chat_json)
    monkeypatch.setattr("app.services.tts.synthesize", fake_synthesize)

    creds = _creds()
    token = client.post("/api/auth/register", json=creds).json()["token"]

    # Initial
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["stats"]["total_sessions"] == 0
    assert r.json()["stats"]["total_messages"] == 0

    # Init chat session (no user attached because no Bearer on init)
    r = client.post(
        "/api/chat/init",
        data={"language": "fr", "native_language": "en", "level": "beginner"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]

    # After init: 1 session, 0 messages (init records session, no user message yet)
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["stats"]["total_sessions"] == 1
    assert r.json()["stats"]["total_messages"] == 1  # init assistant message counts as 1

    # Send a chat message
    r = client.post(
        "/api/chat",
        data={"session_id": session_id, "language": "fr", "text": "Bonjour"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    # After chat: 1 session (same), 3 messages (init + user + assistant)
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["stats"]["total_sessions"] == 1
    assert r.json()["stats"]["total_messages"] == 3


def test_expired_token_returns_none(client, monkeypatch):
    """When a token's expiry is past, get_user_by_token returns None."""
    from app.db import user_store

    creds = _creds()
    r = client.post("/api/auth/register", json=creds)
    token = r.json()["token"]

    # Token works now
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200

    # Move the clock forward past the token's 30-day TTL
    future = datetime.now(timezone.utc) + timedelta(days=31)
    monkeypatch.setattr(user_store, "_now", lambda: future)

    # Same token should now be expired
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
