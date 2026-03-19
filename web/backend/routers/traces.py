from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, desc
from db.connection import AsyncSessionFactory
from db.models import Trace, Span, LLMCall, ToolCall, User
from auth import get_optional_user

router = APIRouter(prefix="/api/traces", tags=["traces"])


@router.get("")
async def list_traces(
    limit: int = Query(50, le=200),
    offset: int = 0,
    source: Optional[str] = None,
    status: Optional[str] = None,
    viewer: Optional[User] = Depends(get_optional_user),
):
    async with AsyncSessionFactory() as session:
        q = (
            select(Trace, User)
            .outerjoin(User, Trace.user_id == User.id)
            .order_by(desc(Trace.created_at))
            .limit(limit)
            .offset(offset)
        )
        if source:
            q = q.where(Trace.source == source)
        if status:
            q = q.where(Trace.status == status)
        # Non-admin authenticated users see only their own traces
        if viewer and not viewer.is_admin:
            q = q.where(Trace.user_id == viewer.id)

        result = await session.execute(q)
        return [_trace_dict(t, u) for t, u in result.all()]


@router.get("/{trace_id}")
async def get_trace(
    trace_id: UUID,
    viewer: Optional[User] = Depends(get_optional_user),
):
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Trace, User)
            .outerjoin(User, Trace.user_id == User.id)
            .where(Trace.id == trace_id)
        )
        row = result.one_or_none()
        if not row:
            raise HTTPException(404, "Trace not found")
        trace, owner = row

        # Non-admin can only access their own traces
        if viewer and not viewer.is_admin and trace.user_id != viewer.id:
            raise HTTPException(403, "Access denied")

        spans_result = await session.execute(
            select(Span).where(Span.trace_id == trace_id).order_by(Span.started_at)
        )
        spans = spans_result.scalars().all()

        span_ids = [s.id for s in spans]
        llm_calls = []
        tool_calls = []
        if span_ids:
            llm_result = await session.execute(
                select(LLMCall).where(LLMCall.span_id.in_(span_ids)).order_by(LLMCall.created_at)
            )
            llm_calls = llm_result.scalars().all()
            tool_result = await session.execute(
                select(ToolCall).where(ToolCall.span_id.in_(span_ids)).order_by(ToolCall.created_at)
            )
            tool_calls = tool_result.scalars().all()

        return {
            **_trace_dict(trace, owner),
            "spans": [_span_dict(s) for s in spans],
            "llm_calls": [_llm_dict(c) for c in llm_calls],
            "tool_calls": [_tool_dict(c) for c in tool_calls],
        }


def _trace_dict(t: Trace, owner: Optional[User] = None) -> dict:
    return {
        "id": str(t.id),
        "source": t.source,
        "status": t.status,
        "started_at": t.created_at.isoformat() if t.created_at else None,
        "ended_at": t.completed_at.isoformat() if t.completed_at else None,
        "input_text": t.user_input,
        "output_text": t.final_output,
        "total_tokens": t.tokens_prompt_total + t.tokens_completion_total,
        "duration_ms": t.duration_ms,
        "error": None,
        "user": owner.username if owner else None,
    }


def _span_dict(s: Span) -> dict:
    return {
        "id": str(s.id),
        "parent_span_id": str(s.parent_span_id) if s.parent_span_id else None,
        "name": s.name,
        "kind": s.span_type,
        "status": s.status,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        "duration_ms": s.duration_ms,
        "error_message": s.error_message,
    }


def _llm_dict(c: LLMCall) -> dict:
    total = (c.tokens_prompt or 0) + (c.tokens_completion or 0)
    return {
        "id": str(c.id),
        "model": c.model,
        "prompt_tokens": c.tokens_prompt,
        "completion_tokens": c.tokens_completion,
        "total_tokens": total,
        "duration_ms": c.duration_ms,
        "stop_reason": c.stop_reason,
        "response_text": c.response,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _tool_dict(c: ToolCall) -> dict:
    return {
        "id": str(c.id),
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
    }
