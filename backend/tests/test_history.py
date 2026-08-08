"""History API tests — requires auth, needs mock services for session data."""
import pytest

FAKE_PAYLOAD = {
    "reply": "Bonjour ! Comment ca va ?",
    "translation": "Hello! How are you?",
    "grammar": {
        "is_correct": False,
        "corrected_text": "Je suis bien.",
        "explanation": "Use 'suis' with 'je'.",
    },
}


@pytest.fixture()
def mock_services(monkeypatch):
    async def fake_chat_json(messages, language="en", native_language="en"):
        return dict(FAKE_PAYLOAD)

    async def fake_synthesize(text, language="en", voice_id=None, level="beginner", force_edge=False):
        return "QUJD"

    monkeypatch.setattr("app.services.llm.chat_json", fake_chat_json)
    monkeypatch.setattr("app.services.tts.synthesize", fake_synthesize)


def _register(client, username: str) -> str:
    """Register a user and return the Bearer token."""
    r = client.post("/api/auth/register", json={"username": username, "password": "s3cret"})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _init_auth(client, token: str, **extra) -> dict:
    """Start a chat session with auth header, return JSON body."""
    headers = {"Authorization": f"Bearer {token}"}
    data = {"language": "fr", "native_language": "en", "level": "beginner", **extra}
    r = client.post("/api/chat/init", data=data, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Auth guards ──────────────────────────────────────────────────


def test_history_requires_auth(client):
    r = client.get("/api/history")
    assert r.status_code == 401


def test_history_detail_requires_auth(client):
    r = client.get("/api/history/some-session")
    assert r.status_code == 401


def test_history_delete_requires_auth(client):
    r = client.delete("/api/history/some-session")
    assert r.status_code == 401


# ── List endpoint ────────────────────────────────────────────────


def test_history_empty_for_new_user(client):
    token = _register(client, "hist_user_empty")
    r = client.get("/api/history", headers=_headers(token))
    assert r.status_code == 200
    assert r.json() == []


def test_history_lists_session_after_creation(client, mock_services):
    token = _register(client, "hist_user_list")
    body = _init_auth(client, token, scenario_id="restaurant")
    session_id = body["session_id"]

    r = client.get("/api/history", headers=_headers(token))
    assert r.status_code == 200
    sessions = r.json()
    assert isinstance(sessions, list)
    matching = [s for s in sessions if s["session_id"] == session_id]
    assert len(matching) == 1


def test_history_list_entry_shape(client, mock_services):
    token = _register(client, "hist_user_shape")
    _init_auth(client, token)

    r = client.get("/api/history", headers=_headers(token))
    assert r.status_code == 200
    sessions = r.json()
    assert len(sessions) >= 1
    entry = sessions[0]
    assert "session_id" in entry
    assert "language" in entry
    assert "level" in entry
    assert "scenario_id" in entry
    assert "started_at" in entry
    assert "last_active" in entry
    assert "message_count" in entry
    assert entry["language"] == "fr"
    assert entry["level"] == "beginner"


# ── Detail endpoint ──────────────────────────────────────────────


def test_history_detail_404_unknown(client):
    token = _register(client, "hist_user_404")
    r = client.get("/api/history/nonexistent-session", headers=_headers(token))
    assert r.status_code == 404


def test_history_delete_404_unknown(client):
    token = _register(client, "hist_user_del404")
    r = client.delete("/api/history/nonexistent-session", headers=_headers(token))
    assert r.status_code == 404


def test_history_detail_message_shape(client, mock_services):
    token = _register(client, "hist_user_msgs")
    init_body = _init_auth(client, token)
    session_id = init_body["session_id"]

    # Send a chat turn so user + assistant messages exist
    r = client.post(
        "/api/chat",
        data={"session_id": session_id, "language": "fr", "text": "Je suis bien"},
    )
    assert r.status_code == 200, r.text

    # Fetch detail
    r = client.get(f"/api/history/{session_id}", headers=_headers(token))
    assert r.status_code == 200
    detail = r.json()

    # Top-level keys
    assert "session" in detail
    assert "messages" in detail

    # Session summary fields
    sess = detail["session"]
    assert sess["session_id"] == session_id
    assert sess["language"] == "fr"
    assert sess["level"] == "beginner"
    assert isinstance(sess["message_count"], int)
    assert sess["message_count"] >= 2

    # Messages — after init + one chat turn there are 3:
    #   assistant (greeting), user (text), assistant (reply)
    messages = detail["messages"]
    assert len(messages) >= 2
    for msg in messages:
        assert "role" in msg
        assert "text" in msg
        assert "created_at" in msg
        assert msg["role"] in ("user", "assistant")
        assert isinstance(msg["text"], str)
        assert isinstance(msg["created_at"], str)

    # First message is the greeting
    assert messages[0]["role"] == "assistant"
    assert messages[0]["translation"] is not None

    # Second message is the user turn we sent
    assert messages[1]["role"] == "user"
    assert messages[1]["text"] == "Je suis bien"


def test_history_detail_types(client, mock_services):
    """Verify each field type in the session detail response."""
    token = _register(client, "hist_user_types")
    init_body = _init_auth(client, token)
    session_id = init_body["session_id"]

    r = client.get(f"/api/history/{session_id}", headers=_headers(token))
    assert r.status_code == 200
    detail = r.json()

    s = detail["session"]
    assert isinstance(s["session_id"], str)
    assert isinstance(s["language"], str)
    assert isinstance(s["level"], str)
    assert isinstance(s["started_at"], str)
    assert isinstance(s["last_active"], str)
    assert isinstance(s["message_count"], int)

    assert isinstance(detail["messages"], list)
    for msg in detail["messages"]:
        assert isinstance(msg["role"], str)
        assert isinstance(msg["text"], str)
        assert isinstance(msg["created_at"], str)
        # nullable fields
        assert msg["translation"] is None or isinstance(msg["translation"], str)
        assert "romanization" not in msg


def test_history_delete_removes_session(client, mock_services):
    token = _register(client, "hist_user_del")
    init_body = _init_auth(client, token)
    session_id = init_body["session_id"]

    # Delete
    r = client.delete(f"/api/history/{session_id}", headers=_headers(token))
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    # Should now be 404
    r = client.get(f"/api/history/{session_id}", headers=_headers(token))
    assert r.status_code == 404


def test_history_scoped_to_user(client, mock_services):
    """Each user only sees their own sessions in history."""
    token_a = _register(client, "hist_user_scoped_a")
    token_b = _register(client, "hist_user_scoped_b")

    # User A creates a session
    body_a = _init_auth(client, token_a)
    session_a = body_a["session_id"]

    # User B should not see A's session
    r_b = client.get("/api/history", headers=_headers(token_b))
    assert r_b.status_code == 200
    b_sessions = r_b.json()
    assert all(s["session_id"] != session_a for s in b_sessions)

    # A should still see their own session
    r_a = client.get("/api/history", headers=_headers(token_a))
    assert r_a.status_code == 200
    a_sessions = r_a.json()
    assert any(s["session_id"] == session_a for s in a_sessions)
