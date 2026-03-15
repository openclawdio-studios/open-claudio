from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import select, desc
from db.connection import AsyncSessionFactory
from db.models import Trace, Span, LLMCall, ToolCall

router = APIRouter(prefix="/api/traces", tags=["traces"])


@router.get("")
async def list_traces(
    limit: int = Query(50, le=200),
    offset: int = 0,
    source: Optional[str] = None,
    status: Optional[str] = None,
):
    async with AsyncSessionFactory() as session:
        q = select(Trace).order_by(desc(Trace.created_at)).limit(limit).offset(offset)
        if source:
            q = q.where(Trace.source == source)
        if status:
            q = q.where(Trace.status == status)
        result = await session.execute(q)
        traces = result.scalars().all()
        return [_trace_dict(t) for t in traces]


@router.get("/{trace_id}")
async def get_trace(trace_id: UUID):
    async with AsyncSessionFactory() as session:
        trace = await session.get(Trace, trace_id)
        if not trace:
            raise HTTPException(404, "Trace not found")

        spans_result = await session.execute(
            select(Span).where(Span.trace_id == trace_id).order_by(Span.started_at)
        )
        spans = spans_result.scalars().all()

        # LLM calls via span_id join
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
            **_trace_dict(trace),
            "spans": [_span_dict(s) for s in spans],
            "llm_calls": [_llm_dict(c) for c in llm_calls],
            "tool_calls": [_tool_dict(c) for c in tool_calls],
        }


def _trace_dict(t: Trace) -> dict:
    total_tokens = t.tokens_prompt_total + t.tokens_completion_total
    return {
        "id": str(t.id),
        "source": t.source,
        "status": t.status,
        "started_at": t.created_at.isoformat() if t.created_at else None,
        "ended_at": t.completed_at.isoformat() if t.completed_at else None,
        "input_text": t.user_input,
        "output_text": t.final_output,
        "total_tokens": total_tokens,
        "duration_ms": t.duration_ms,
        "error": None,
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
