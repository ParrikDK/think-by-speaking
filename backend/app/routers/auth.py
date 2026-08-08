"""Auth router — register / login / logout / me.

Auth is optional everywhere else; these are the only endpoints that issue
or require tokens. Passwords: PBKDF2-HMAC-SHA256 (100k iters, per-user
salt). Tokens: 32-byte hex, 30-day expiry.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from ..db.stats_store import get_stats
from ..db.user_store import User, user_store
from ..models.schemas import AuthRequest, AuthResponse, MeResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _bearer_token(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip() or None
    return None


async def get_optional_user(request: Request) -> Optional[User]:
    """Resolve Bearer token → User, or None. Never raises (guest mode)."""
    token = _bearer_token(request)
    if not token:
        return None
    try:
        return await user_store.get_user_by_token(token)
    except Exception:
        return None


async def require_user(user: Optional[User] = Depends(get_optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "Not authenticated")
    return user


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(body: AuthRequest):
    user = await user_store.create_user(body.username.strip(), body.password)
    if user is None:
        raise HTTPException(409, "Username already taken")
    token = await user_store.create_token(user.id)
    return AuthResponse(token=token, user=UserOut(**vars(user)))


@router.post("/login", response_model=AuthResponse)
async def login(body: AuthRequest):
    user = await user_store.verify_credentials(body.username.strip(), body.password)
    if user is None:
        raise HTTPException(401, "Invalid username or password")
    token = await user_store.create_token(user.id)
    return AuthResponse(token=token, user=UserOut(**vars(user)))


@router.post("/logout")
async def logout(request: Request):
    token = _bearer_token(request)
    if token:
        await user_store.delete_token(token)
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(require_user)):
    stats = await get_stats(user.id)
    return MeResponse(user=UserOut(**vars(user)), stats=stats)
