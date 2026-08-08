"""Languages catalog API test — GET /api/languages."""
from app.prompts.tutor import LANGUAGE_NAMES


def test_list_languages(client):
    r = client.get("/api/languages")
    assert r.status_code == 200
    langs = r.json()
    assert isinstance(langs, list)
    assert len(langs) > 0


def test_language_item_shape(client):
    r = client.get("/api/languages")
    for lang in r.json():
        assert "code" in lang
        assert "name" in lang
        assert "native_name" in lang
        assert "romanization" not in lang
        assert "tts" in lang


def test_en_in_languages(client):
    r = client.get("/api/languages")
    codes = [lang["code"] for lang in r.json()]
    assert "en" in codes


def test_languages_sorted_by_name(client):
    r = client.get("/api/languages")
    langs = r.json()
    names = [lang["name"] for lang in langs]
    assert names == sorted(names)


def test_language_tts_provider(client):
    r = client.get("/api/languages")
    for lang in r.json():
        assert lang["tts"] in ("edge", "elevenlabs")


def test_no_language_has_romanization_flag(client):
    r = client.get("/api/languages")
    for lang in r.json():
        assert "romanization" not in lang


def test_total_languages_matches_source(client):
    r = client.get("/api/languages")
    assert len(r.json()) == len(LANGUAGE_NAMES)
