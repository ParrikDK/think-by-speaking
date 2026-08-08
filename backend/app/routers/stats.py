"""Stats endpoint — Bearer auth required."""
from fastapi import APIRouter, Depends

from ..db.session_store import session_store
from ..db.stats_store import get_stats
from ..db.user_store import User
from ..models.schemas import FullStats
from .auth import require_user

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=FullStats)
async def stats(user: User = Depends(require_user)):
    await session_store.flush()  # minutes/sessions reflect write-behind rows
    return await get_stats(user.id, include_recent=True)
