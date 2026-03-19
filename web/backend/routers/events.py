from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from db.connection import AsyncSessionFactory
from db.models import EventRecord, Trace, User
from auth import get_optional_user

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
async def list_events(
    limit: int = Query(50, le=200),
    offset: int = 0,
    source: Optional[str] = None,
    viewer: Optional[User] = Depends(get_optional_user),
):
    async with AsyncSessionFactory() as session:
        q = (
            select(EventRecord, User)
            .outerjoin(Trace, EventRecord.trace_id == Trace.id)
            .outerjoin(User, Trace.user_id == User.id)
            .order_by(desc(EventRecord.received_at))
            .limit(limit)
            .offset(offset)
        )
        if source:
            q = q.where(EventRecord.source == source)
        # Non-admin: only events linked to their own traces
        if viewer and not viewer.is_admin:
            q = q.where(Trace.user_id == viewer.id)

        result = await session.execute(q)
        return [_event_dict(e, u) for e, u in result.all()]


def _event_dict(e: EventRecord, owner: Optional[User] = None) -> dict:
    return {
        "id": str(e.id),
        "trace_id": str(e.trace_id) if e.trace_id else None,
        "source": e.source,
        "event_type": e.event_type,
        "topic": e.topic,
        "payload": e.payload,
        "route_matched": e.route_matched,
        "status": "processed" if e.processed_at else "received",
        "received_at": e.received_at.isoformat() if e.received_at else None,
        "processed_at": e.processed_at.isoformat() if e.processed_at else None,
        "processing_ms": e.processing_ms,
        "user": owner.username if owner else None,
    }
