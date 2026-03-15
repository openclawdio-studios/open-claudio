from typing import Optional
from fastapi import APIRouter, Query
from sqlalchemy import select, desc
from db.connection import AsyncSessionFactory
from db.models import EventRecord

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
async def list_events(
    limit: int = Query(50, le=200),
    offset: int = 0,
    source: Optional[str] = None,
):
    async with AsyncSessionFactory() as session:
        q = select(EventRecord).order_by(desc(EventRecord.received_at)).limit(limit).offset(offset)
        if source:
            q = q.where(EventRecord.source == source)
        result = await session.execute(q)
        events = result.scalars().all()
        return [_event_dict(e) for e in events]


def _event_dict(e: EventRecord) -> dict:
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
    }
