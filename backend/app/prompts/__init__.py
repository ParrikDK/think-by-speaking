"""Scenario loading from app/prompts/scenarios/*.yaml.

Each YAML file provides: id, title, description, icon (emoji), prompt
(the role-play instruction injected into the tutor system prompt).
"""
from functools import lru_cache
from pathlib import Path

import yaml

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"

REQUIRED_FIELDS = ("id", "title", "description", "icon", "prompt")

# User-directed 2026-08-04: these ids lead the scenario picker (Free talk
# is the frontend's always-first default chip); the rest follow by id.
DISPLAY_FIRST = ("at-work", "small-talk")


@lru_cache
def load_scenarios() -> list[dict]:
    """Load all scenario definitions. DISPLAY_FIRST ids lead, the rest
    follow sorted by id (was: purely alphabetical). Cached."""
    scenarios = []
    for path in SCENARIOS_DIR.glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        missing = [f for f in REQUIRED_FIELDS if f not in data]
        if missing:
            raise ValueError(f"Scenario {path.name} missing fields: {missing}")
        scenarios.append({f: data[f] for f in REQUIRED_FIELDS})
    by_id = {s["id"]: s for s in scenarios}
    leading = [by_id[sid] for sid in DISPLAY_FIRST if sid in by_id]
    trailing = sorted(
        (s for s in scenarios if s["id"] not in DISPLAY_FIRST), key=lambda s: s["id"]
    )
    return leading + trailing


def get_scenario(scenario_id: str) -> dict | None:
    for s in load_scenarios():
        if s["id"] == scenario_id:
            return s
    return None


def scenario_summaries() -> list[dict]:
    """Public shape for GET /api/scenarios (prompt template stays server-side)."""
    return [
        {"id": s["id"], "title": s["title"], "description": s["description"], "icon": s["icon"]}
        for s in load_scenarios()
    ]
