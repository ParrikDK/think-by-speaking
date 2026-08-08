"""Config sanity: defaults, derived properties, no dead settings."""
from app.config import Settings, get_settings


def _defaults() -> Settings:
    """Settings built from code defaults only (ignores the real .env)."""
    return Settings(_env_file=None)


def test_defaults():
    s = _defaults()
    assert s.deepseek_model == "deepseek-v4-pro"
    assert s.deepseek_model_fast == "deepseek-v4-flash"
    assert s.port == 8000  # canonical port
    assert s.session_ttl_minutes == 30
    assert s.token_ttl_days == 30
    assert s.rate_limit_per_minute == 60
    assert s.flush_interval_seconds == 10


def test_retired_model_names_trigger_startup_warning():
    """DeepSeek retired deepseek-chat/-reasoner/-flash on 2026-07-24 —
    startup must warn loudly (naming the replacement), never crash."""
    from loguru import logger

    from app.config import warn_on_retired_models

    records = []
    sink_id = logger.add(lambda m: records.append(m.record["message"]), level="WARNING")
    try:
        warn_on_retired_models(_defaults())  # v4 defaults → silent
        assert records == []
        warn_on_retired_models(Settings(_env_file=None, deepseek_model="deepseek-chat"))
    finally:
        logger.remove(sink_id)
    assert len(records) == 1
    assert "deepseek-chat" in records[0] and "deepseek-v4-pro" in records[0]


def test_allowed_origins_list():
    origins = _defaults().allowed_origins_list
    assert isinstance(origins, list) and origins
    assert all(o.startswith("http") for o in origins)
    # env-file parsing also works (comma-separated string)
    assert Settings(allowed_origins="http://a,http://b").allowed_origins_list == [
        "http://a",
        "http://b",
    ]


def test_database_path_parsing():
    s = get_settings()
    assert s.database_url.startswith("sqlite:///")
    assert not s.database_path.startswith("sqlite")
    # tests run against a temp db, never the real one
    assert "tutor_test_" in s.database_path


def test_api_keys_come_from_env_not_real_env_file():
    s = get_settings()
    assert s.deepseek_api_key == "test-key"
    assert s.elevenlabs_api_key == "test-key"
