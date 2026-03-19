"""
API key authentication for Open-Claudio.

Usage:
    from auth import get_current_user, require_admin
    from db.models import User

    @router.get("/protected")
    async def endpoint(user: User = Depends(get_current_user)):
        ...

    @router.get("/admin-only")
    async def admin_endpoint(user: User = Depends(require_admin)):
        ...
"""

import hashlib
from datetime import datetime
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select, update as sa_update

from db.connection import AsyncSessionFactory
from db.models import ApiKey, User


async def get_current_user(authorization: Optional[str] = Header(None)) -> User:
    """Validate an API key and return the associated User.

    Raises 401 if the header is missing, the key is invalid, or the user is inactive.
    Updates last_used_at / last_seen_at as a side effect.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    raw_key = authorization.removeprefix("Bearer ").strip()
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                result = await session.execute(
                    select(ApiKey, User)
                    .join(User, ApiKey.user_id == User.id)
                    .where(
                        ApiKey.key_hash == key_hash,
                        ApiKey.is_active.is_(True),
                        User.is_active.is_(True),
                    )
                )
                row = result.one_or_none()
                if row is None:
                    raise HTTPException(status_code=401, detail="Invalid or inactive API key")

                api_key, user = row
                now = datetime.utcnow()
                await session.execute(
                    sa_update(ApiKey).where(ApiKey.id == api_key.id).values(last_used_at=now)
                )
                await session.execute(
                    sa_update(User).where(User.id == user.id).values(last_seen_at=now)
                )
                # Detach the user object so it remains accessible after session closes
                session.expunge(user)
        return user
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Auth error: {exc}")


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Like get_current_user but also asserts is_admin == True."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def get_optional_user(authorization: Optional[str] = Header(None)) -> Optional[User]:
    """Returns None for anonymous requests, validates key if present.

    Anonymous → caller sees all data (admin-like view).
    Authenticated non-admin → caller sees only their own data.
    Authenticated admin → caller sees all data.
    """
    if not authorization:
        return None
    return await get_current_user(authorization)
