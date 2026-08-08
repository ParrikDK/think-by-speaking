"""User accounts + bearer tokens.

Passwords: PBKDF2-HMAC-SHA256 (stdlib hashlib, 100k iterations, per-user salt),
stored as "<salt_hex>$<hash_hex>". Tokens: random 32-byte hex, 30-day expiry.
"""
import hashlib
import hmac
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..config import get_settings
from .database import get_db

_PBKDF2_ITERATIONS = 100_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_password(password: str, salt: bytes) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, expected = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), _PBKDF2_ITERATIONS
        )
        return hmac.compare_digest(dk.hex(), expected)
    except (ValueError, TypeError):
        return False


@dataclass
class User:
    id: str
    username: str
    created_at: str


class UserStore:
    # ── users ──

    async def create_user(self, username: str, password: str) -> Optional[User]:
        db = get_db()
        async with db.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ) as cur:
            if await cur.fetchone():
                return None  # username taken
        user = User(
            id=uuid.uuid4().hex,
            username=username,
            created_at=_now().isoformat(),
        )
        import secrets

        password_hash = _hash_password(password, secrets.token_bytes(16))
        try:
            await db.execute(
                "INSERT INTO users (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (user.id, user.username, password_hash, user.created_at),
            )
            await db.execute(
                "INSERT INTO user_stats (user_id, total_sessions, total_messages) VALUES (?, 0, 0)",
                (user.id,),
            )
            await db.commit()
        except sqlite3.IntegrityError:
            # Concurrent registration with the same username — the SELECT
            # above raced. Treat as taken (409), not a 500.
            return None
        return user

    async def verify_credentials(self, username: str, password: str) -> Optional[User]:
        db = get_db()
        async with db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ) as cur:
            row = await cur.fetchone()
        if row is None or not _verify_password(password, row["password_hash"]):
            return None
        return User(id=row["id"], username=row["username"], created_at=row["created_at"])

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        db = get_db()
        async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return User(id=row["id"], username=row["username"], created_at=row["created_at"])

    # ── tokens ──

    async def create_token(self, user_id: str) -> str:
        import secrets

        token = secrets.token_hex(32)
        now = _now()
        expires = now + timedelta(days=get_settings().token_ttl_days)
        db = get_db()
        await db.execute(
            "INSERT INTO tokens (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now.isoformat(), expires.isoformat()),
        )
        await db.commit()
        return token

    async def get_user_by_token(self, token: str) -> Optional[User]:
        db = get_db()
        async with db.execute("SELECT * FROM tokens WHERE token = ?", (token,)) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        expires = datetime.fromisoformat(row["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < _now():
            await self.delete_token(token)
            return None
        return await self.get_user_by_id(row["user_id"])

    async def delete_token(self, token: str) -> None:
        db = get_db()
        await db.execute("DELETE FROM tokens WHERE token = ?", (token,))
        await db.commit()


user_store = UserStore()
