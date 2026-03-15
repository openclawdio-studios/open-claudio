from typing import Optional
from fastapi import APIRouter, Query
from sqlalchemy import select, desc
from db.connection import AsyncSessionFactory
from db.models import ToolCall

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("/calls")
async def list_tool_calls(
    limit: int = Query(50, le=200),
    offset: int = 0,
    tool_name: Optional[str] = None,
    success: Optional[bool] = None,
):
    async with AsyncSessionFactory() as session:
        q = select(ToolCall).order_by(desc(ToolCall.created_at)).limit(limit).offset(offset)
        if tool_name:
            q = q.where(ToolCall.tool_name == tool_name)
        if success is not None:
            q = q.where(ToolCall.success == success)
        result = await session.execute(q)
        calls = result.scalars().all()
        return [{
            "id": str(c.id),
            "span_id": str(c.span_id),
            "tool_name": c.tool_name,
            "tool_source": c.tool_source,
            "arguments": c.input_args,
            "result": c.output,
            "success": c.success,
            "error_type": c.error_type,
            "healing_strategy": c.healing_strategy,
            "duration_ms": c.duration_ms,
            "retries": c.retries,
            "known_fix_applied": c.known_fix_applied,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        } for c in calls]
