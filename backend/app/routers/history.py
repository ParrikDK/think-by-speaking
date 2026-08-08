"""History endpoints — Bearer auth required."""
from fastapi import APIRouter, Depends, HTTPException

from ..db import stats_store
from ..db.session_store import session_store
from ..db.user_store import User
from ..models.schemas import SessionDetail, SessionSummary
from .auth import require_user

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=list[SessionSummary])
async def list_history(user: User = Depends(require_user)):
    await session_store.flush()  # make sure write-behind rows are visible
    return await stats_store.list_sessions(user.id)


@router.get("/{session_id}", response_model=SessionDetail)
async def get_history_session(session_id: str, user: User = Depends(require_user)):
    await session_store.flush()
    detail = await stats_store.get_session_detail(user.id, session_id)
    if detail is None:
        raise HTTPException(404, "Session not found")
    return detail


@router.delete("/{session_id}")
async def delete_history_session(session_id: str, user: User = Depends(require_user)):
    await session_store.flush()
    session_store.evict(session_id)  # drop from cache if present
    deleted = await stats_store.delete_session(user.id, session_id)
    if not deleted:
        raise HTTPException(404, "Session not found")
    return {"ok": True}
