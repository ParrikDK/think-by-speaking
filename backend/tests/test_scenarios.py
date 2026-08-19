"""Scenario catalog: YAML files load with all required fields.

v13: scenarios repurposed as debate subjects (general interest, user-directed:
"just generally a debate person, so that I think by speaking").
"""
from app.prompts import REQUIRED_FIELDS, get_scenario, load_scenarios, scenario_summaries

EXPECTED_IDS = {
    "social-media", "ai-future", "remote-work", "money-happiness",
    "school-start", "free-will", "zoos", "gaming", "voting",
}


def test_all_scenarios_load():
    scenarios = load_scenarios()
    assert len(scenarios) == 9
    assert {s["id"] for s in scenarios} == EXPECTED_IDS


def test_scenario_order_leads_with_social_media_ai_future():
    """DISPLAY_FIRST: Social Media + AI lead the picker; the remainder stays
    alphabetical by id (Free talk is a frontend chip rendered first)."""
    ids = [s["id"] for s in load_scenarios()]
    assert ids[:2] == ["social-media", "ai-future"]
    assert ids[2:] == sorted(ids[2:])


def test_required_fields():
    for s in load_scenarios():
        for field in REQUIRED_FIELDS:
            assert field in s and s[field], f"{s.get('id')} missing {field}"
        assert len(s["icon"]) <= 4  # emoji


def test_summaries_hide_prompt():
    for summary in scenario_summaries():
        assert set(summary.keys()) == {"id", "title", "description", "icon", "interests"}


def test_get_scenario():
    assert get_scenario("social-media")["title"] == "Is Social Media Bad for Society?"
    assert get_scenario("nope") is None


# ── API endpoint ─────────────────────────────────────────────────


def test_api_list_scenarios(client):
    r = client.get("/api/scenarios")
    assert r.status_code == 200
    scenarios = r.json()
    assert isinstance(scenarios, list)
    assert len(scenarios) == 9


def test_api_scenario_item_shape(client):
    r = client.get("/api/scenarios")
    for s in r.json():
        assert "id" in s
        assert "title" in s
        assert "description" in s
        assert "icon" in s
        assert set(s.keys()) == {"id", "title", "description", "icon", "interests"}


def test_api_scenario_types(client):
    r = client.get("/api/scenarios")
    for s in r.json():
        assert isinstance(s["id"], str) and s["id"]
        assert isinstance(s["title"], str) and s["title"]
        assert isinstance(s["description"], str) and s["description"]
        assert isinstance(s["icon"], str) and len(s["icon"]) <= 4


def test_api_scenario_language_parameter_ignored(client):
    r = client.get("/api/scenarios?language=fr")
    assert r.status_code == 200
    scenarios = r.json()
    assert len(scenarios) == 9
