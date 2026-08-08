"""Scenarios catalog (loaded from app/prompts/scenarios/*.yaml)."""
from fastapi import APIRouter

from ..models.schemas import ScenarioOut
from ..prompts import scenario_summaries

router = APIRouter(tags=["scenarios"])


@router.get("/scenarios", response_model=list[ScenarioOut])
async def list_scenarios(language: str | None = None):
    # `language` is reserved for future localized titles — return all for now.
    return scenario_summaries()
