"""
Admin router — user management and token quota administration.
All endpoints require a valid API key with is_admin=True.
"""

import hashlib
import secrets
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from auth import require_admin
from db.connection import AsyncSessionFactory
from db.models import ApiKey, TokenQuota, Trace, User

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class CreateUserBody(BaseModel):
    username: str
    display_name: Optional[str] = None
    daily_tokens: int = 100_000   # -1 = unlimited
    is_admin: bool = False


class UpdateUserBody(BaseModel):
    display_name: Optional[str] = None
    is_active: Optional[bool] = None
    daily_tokens: Optional[int] = None


class CreateKeyBody(BaseModel):
    name: Optional[str] = "API key"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_key() -> tuple[str, str, str]:
    """Generate (raw_key, sha256_hash, prefix)."""
    raw = "clau-" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    prefix = raw[:13]
    return raw, key_hash, prefix


def _now() -> datetime:
    return datetime.utcnow()


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(_admin: User = Depends(require_admin)):
    """List all users with their quota and today's token usage."""
    async with AsyncSessionFactory() as session:
        # All users + their quotas
        rows = await session.execute(
            select(User, TokenQuota)
            .outerjoin(TokenQuota, TokenQuota.user_id == User.id)
            .order_by(User.created_at)
        )
        users = rows.all()

        # Today's usage per user (raw SQL for reliable date cast)
        from sqlalchemy import text
        usage_raw = await session.execute(text("""
            SELECT user_id,
                   COALESCE(SUM(tokens_prompt_total + tokens_completion_total), 0) AS used
            FROM traces
            WHERE user_id IS NOT NULL
              AND created_at::date = CURRENT_DATE
              AND status NOT IN ('running')
            GROUP BY user_id
        """))
        usage_map = {str(r.user_id): int(r.used) for r in usage_raw}

        # Keys count per user
        keys_rows = await session.execute(
            select(ApiKey.user_id, func.count().label("cnt"))
            .where(ApiKey.is_active.is_(True))
            .group_by(ApiKey.user_id)
        )
        keys_map = {str(r.user_id): r.cnt for r in keys_rows}

    return [
        {
            "id": str(u.id),
            "username": u.username,
            "display_name": u.display_name,
            "is_active": u.is_active,
            "is_admin": u.is_admin,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
            "daily_tokens": q.daily_tokens if q else -1,
            "tokens_used_today": usage_map.get(str(u.id), 0),
            "api_keys_count": keys_map.get(str(u.id), 0),
        }
        for u, q in users
    ]


@router.post("/users", status_code=201)
async def create_user(body: CreateUserBody, _admin: User = Depends(require_admin)):
    """Create a new user and configure their daily token quota."""
    async with AsyncSessionFactory() as session:
        async with session.begin():
            existing = await session.execute(
                select(User).where(User.username == body.username)
            )
            if existing.scalar_one_or_none():
                raise HTTPException(409, f"Username '{body.username}' already exists")

            uid = uuid.uuid4()
            now = _now()
            session.add(User(
                id=uid,
                username=body.username,
                display_name=body.display_name,
                is_active=True,
                is_admin=body.is_admin,
                created_at=now,
            ))
            await session.flush()   # commit User to DB before FK reference in token_quotas
            session.add(TokenQuota(
                user_id=uid,
                daily_tokens=body.daily_tokens,
                updated_at=now,
            ))

    return {"id": str(uid), "username": body.username}


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UpdateUserBody,
    _admin: User = Depends(require_admin),
):
    """Update display_name, is_active, or daily_tokens for a user."""
    uid = _parse_uuid(user_id)
    async with AsyncSessionFactory() as session:
        async with session.begin():
            user_values = {}
            if body.display_name is not None:
                user_values["display_name"] = body.display_name
            if body.is_active is not None:
                user_values["is_active"] = body.is_active
            if user_values:
                await session.execute(
                    sa_update(User).where(User.id == uid).values(**user_values)
                )
            if body.daily_tokens is not None:
                await session.execute(
                    pg_insert(TokenQuota)
                    .values(user_id=uid, daily_tokens=body.daily_tokens, updated_at=_now())
                    .on_conflict_do_update(
                        index_elements=["user_id"],
                        set_={"daily_tokens": body.daily_tokens, "updated_at": _now()},
                    )
                )
    return {"status": "updated"}


@router.delete("/users/{user_id}")
async def deactivate_user(user_id: str, _admin: User = Depends(require_admin)):
    """Soft-delete a user (sets is_active=False). Does not delete observability data."""
    uid = _parse_uuid(user_id)
    async with AsyncSessionFactory() as session:
        async with session.begin():
            await session.execute(
                sa_update(User).where(User.id == uid).values(is_active=False)
            )
    return {"status": "deactivated"}


# ── API Keys ──────────────────────────────────────────────────────────────────

@router.get("/users/{user_id}/keys")
async def list_keys(user_id: str, _admin: User = Depends(require_admin)):
    """List active API keys for a user (prefix only — never the full key)."""
    uid = _parse_uuid(user_id)
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(ApiKey)
            .where(ApiKey.user_id == uid, ApiKey.is_active.is_(True))
            .order_by(ApiKey.created_at)
        )
        keys = result.scalars().all()
    return [
        {
            "id": str(k.id),
            "key_prefix": k.key_prefix,
            "name": k.name,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        }
        for k in keys
    ]


@router.post("/users/{user_id}/keys", status_code=201)
async def create_key(
    user_id: str,
    body: CreateKeyBody,
    _admin: User = Depends(require_admin),
):
    """Generate a new API key for a user. The raw key is returned ONCE — store it safely."""
    uid = _parse_uuid(user_id)
    raw_key, key_hash, key_prefix = _make_key()
    kid = uuid.uuid4()
    now = _now()

    async with AsyncSessionFactory() as session:
        async with session.begin():
            user = await session.get(User, uid)
            if not user:
                raise HTTPException(404, "User not found")
            session.add(ApiKey(
                id=kid,
                user_id=uid,
                key_hash=key_hash,
                key_prefix=key_prefix,
                name=body.name,
                is_active=True,
                created_at=now,
            ))

    return {
        "id": str(kid),
        "key_prefix": key_prefix,
        "name": body.name,
        "raw_key": raw_key,   # ← shown ONCE, never stored again
        "created_at": now.isoformat(),
    }


@router.delete("/users/{user_id}/keys/{key_id}")
async def revoke_key(
    user_id: str,
    key_id: str,
    _admin: User = Depends(require_admin),
):
    """Revoke (deactivate) an API key."""
    uid = _parse_uuid(user_id)
    kid = _parse_uuid(key_id)
    async with AsyncSessionFactory() as session:
        async with session.begin():
            await session.execute(
                sa_update(ApiKey)
                .where(ApiKey.id == kid, ApiKey.user_id == uid)
                .values(is_active=False)
            )
    return {"status": "revoked"}


# ── Utility ───────────────────────────────────────────────────────────────────

def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(400, f"Invalid UUID: {value!r}")
