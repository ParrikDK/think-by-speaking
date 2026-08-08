"""Test bootstrap — a temp SQLite db and dummy API keys are set BEFORE the
app package is imported, so tests never touch real data or real credentials.
"""
import atexit
import os
import shutil
import tempfile

_TMPDIR = tempfile.mkdtemp(prefix="tutor_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMPDIR}/test.db"
os.environ["DEEPSEEK_API_KEY"] = "test-key"
os.environ["ELEVENLABS_API_KEY"] = "test-key"
# Pin TTS provider selection: tests default to edge-first for every
# language (individual tests flip the cached settings via monkeypatch).
os.environ["ELEVENLABS_PRIMARY_LANGUAGES"] = ""
os.environ["ENVIRONMENT"] = "test"


@atexit.register
def _cleanup_tempdir():
    shutil.rmtree(_TMPDIR, ignore_errors=True)

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

get_settings.cache_clear()


@pytest.fixture()
def client():
    """TestClient with fresh app instance (not the module-level singleton,
    so each test gets its own rate-limiter bucket and no cross-test bleed)."""
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
