"""Health check."""
import time

from fastapi import APIRouter

from .. import __version__
from ..db.session_store import session_store
from ..models.schemas import HealthOut

router = APIRouter(tags=["health"])

_started_at = time.time()


@router.get("/health", response_model=HealthOut)
async def health():
    return HealthOut(
        status="ok",
        version=__version__,
        uptime_s=int(time.time() - _started_at),
        active_sessions=session_store.active_count(),
    )
