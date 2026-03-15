"""
Recorder — high-level async functions to persist observability data.

Design principles:
  1. NEVER raises — all functions are try/except wrapped.
     A DB failure must NEVER crash or slow down the agent.
  2. Uses contextvars to propagate trace_id and parent_span_id through
     the async call stack without changing any function signatures.
  3. Can be disabled at startup (DB unavailable) — all calls become no-ops.

Context variable usage:
  set_trace_id()       → call once at the start of each user request
  set_parent_span_id() → call before delegating to a child coroutine
  reset_parent_span_id(token) → call after the child returns (restores parent)
"""

import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

from db.connection import AsyncSessionFactory
from db.models import (
    EventRecord,
    LLMCall,
    RagRetrieval,
    Span,
    ToolCall,
    ToolFixLog,
    Trace,
)

logger = logging.getLogger("recorder")

# ---------------------------------------------------------------------------
# Global enable flag — set to True only when DB is reachable at startup
# ---------------------------------------------------------------------------
_enabled: bool = False


async def init() -> bool:
    """
    Test DB connectivity and enable recording if successful.
    Call once during application startup.
    """
    global _enabled
    from db.connection import check_connection

    _enabled = await check_connection()
    if _enabled:
        logger.info("DB recorder enabled.")
    else:
        logger.warning("DB recorder DISABLED — observability data will not be persisted.")
    return _enabled


# ---------------------------------------------------------------------------
# Context variables — propagate automatically through asyncio task trees
# ---------------------------------------------------------------------------

_trace_id_var: ContextVar[Optional[uuid.UUID]] = ContextVar("trace_id", default=None)
_parent_span_id_var: ContextVar[Optional[uuid.UUID]] = ContextVar("parent_span_id", default=None)


def get_trace_id() -> Optional[uuid.UUID]:
    return _trace_id_var.get()


def get_parent_span_id() -> Optional[uuid.UUID]:
    return _parent_span_id_var.get()


def set_trace_id(tid: uuid.UUID):
    """Set the current trace ID. Returns a Token for reset."""
    return _trace_id_var.set(tid)


def set_parent_span_id(sid: Optional[uuid.UUID]):
    """Set the current parent span ID. Returns a Token for reset."""
    return _parent_span_id_var.set(sid)


def reset_parent_span_id(token):
    """Restore the parent span ID to its previous value using the Token."""
    _parent_span_id_var.reset(token)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

async def _persist(obj) -> None:
    """Add and commit a single ORM object. Silently swallows all errors."""
    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                session.add(obj)
    except Exception as exc:
        logger.warning("DB persist failed (%s): %s", type(obj).__name__, exc)


def _now() -> datetime:
    return datetime.utcnow()


def _serialize_messages(messages: list) -> list:
    """Convert a mix of dicts and OpenAI message objects to plain dicts."""
    result = []
    for m in messages:
        if isinstance(m, dict):
            result.append(m)
        else:
            d = {"role": getattr(m, "role", ""), "content": getattr(m, "content", "") or ""}
            if getattr(m, "tool_calls", None):
                d["tool_calls"] = [
                    {
                        "id": tc.id,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in m.tool_calls
                ]
            result.append(d)
    return result


# ---------------------------------------------------------------------------
# Traces
# ---------------------------------------------------------------------------

async def start_trace(source: str, user_input: str) -> Optional[uuid.UUID]:
    """
    Create a new Trace row and store its ID in the context var.
    Returns the trace UUID, or None if recording is disabled.
    """
    if not _enabled:
        return None
    tid = uuid.uuid4()
    trace = Trace(id=tid, source=source, user_input=user_input, status="running")
    await _persist(trace)
    set_trace_id(tid)
    return tid


async def complete_trace(
    trace_id: Optional[uuid.UUID],
    output: str,
    status: str,
    duration_ms: int,
    agent_plan: Optional[list] = None,
) -> None:
    if not _enabled or trace_id is None:
        return
    from sqlalchemy import update as sa_update, select, func
    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                # Sum tokens from all llm_calls linked to this trace's spans
                tok = await session.execute(
                    select(
                        func.coalesce(func.sum(LLMCall.tokens_prompt), 0),
                        func.coalesce(func.sum(LLMCall.tokens_completion), 0),
                    ).join(Span, LLMCall.span_id == Span.id)
                    .where(Span.trace_id == trace_id)
                )
                tokens_p, tokens_c = tok.one()
                values: dict = {
                    "final_output": output[:4000],
                    "status": status,
                    "duration_ms": duration_ms,
                    "tokens_prompt_total": int(tokens_p),
                    "tokens_completion_total": int(tokens_c),
                    "completed_at": _now(),
                }
                if agent_plan is not None:
                    values["agent_plan"] = agent_plan
                await session.execute(sa_update(Trace).where(Trace.id == trace_id).values(**values))
    except Exception as exc:
        logger.warning("complete_trace failed: %s", exc)


# ---------------------------------------------------------------------------
# Spans
# ---------------------------------------------------------------------------

async def start_span(span_type: str, name: str) -> Optional[uuid.UUID]:
    """
    Create a Span row as a child of the current context's parent span.
    Returns the new span UUID.
    """
    if not _enabled:
        return None
    trace_id = get_trace_id()
    if trace_id is None:
        return None
    sid = uuid.uuid4()
    span = Span(
        id=sid,
        trace_id=trace_id,
        parent_span_id=get_parent_span_id(),
        span_type=span_type,
        name=name,
        status="running",
    )
    await _persist(span)
    return sid


async def complete_span(
    span_id: Optional[uuid.UUID],
    status: str,
    error_message: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> None:
    if not _enabled or span_id is None:
        return
    from sqlalchemy import update as sa_update
    values: dict = {"status": status, "ended_at": _now()}
    if duration_ms is not None:
        values["duration_ms"] = duration_ms
    if error_message:
        values["error_message"] = error_message[:1000]
    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                await session.execute(sa_update(Span).where(Span.id == span_id).values(**values))
    except Exception as exc:
        logger.warning("complete_span failed: %s", exc)


# ---------------------------------------------------------------------------
# LLM Calls
# ---------------------------------------------------------------------------

async def record_llm_call(
    span_id: Optional[uuid.UUID],
    model: str,
    messages: list,
    response: str,
    tokens_prompt: Optional[int],
    tokens_completion: Optional[int],
    temperature: Optional[float],
    stop_reason: Optional[str],
    duration_ms: int,
) -> None:
    if not _enabled or span_id is None:
        return
    row = LLMCall(
        span_id=span_id,
        model=model,
        messages=_serialize_messages(messages),
        response=response[:8000],
        tokens_prompt=tokens_prompt,
        tokens_completion=tokens_completion,
        temperature=temperature,
        stop_reason=stop_reason,
        duration_ms=duration_ms,
    )
    await _persist(row)


# ---------------------------------------------------------------------------
# Tool Calls
# ---------------------------------------------------------------------------

async def record_tool_call(
    span_id: Optional[uuid.UUID],
    tool_name: str,
    tool_source: str,
    input_args: dict,
    output: str,
    success: bool,
    error_type: Optional[str],
    healing_strategy: Optional[str],
    retries: int,
    known_fix_applied: bool,
    duration_ms: int,
) -> None:
    if not _enabled or span_id is None:
        return
    row = ToolCall(
        span_id=span_id,
        tool_name=tool_name,
        tool_source=tool_source,
        input_args=input_args,
        output=output[:4000],
        success=success,
        error_type=error_type,
        healing_strategy=healing_strategy,
        retries=retries,
        known_fix_applied=known_fix_applied,
        duration_ms=duration_ms,
    )
    await _persist(row)


# ---------------------------------------------------------------------------
# Tool Fix Log
# ---------------------------------------------------------------------------

async def upsert_tool_fix(
    agent_name: str,
    tool_name: str,
    original_args: dict,
    fixed_args: dict,
) -> None:
    """Insert or update a learned parameter correction."""
    if not _enabled:
        return
    try:
        from sqlalchemy import and_
        from sqlalchemy.dialects.postgresql import insert

        async with AsyncSessionFactory() as session:
            async with session.begin():
                stmt = (
                    insert(ToolFixLog)
                    .values(
                        agent_name=agent_name,
                        tool_name=tool_name,
                        original_args=original_args,
                        fixed_args=fixed_args,
                    )
                    .on_conflict_do_update(
                        index_elements=["agent_name", "tool_name", "original_args"],
                        set_={
                            "fixed_args": fixed_args,
                            "times_applied": ToolFixLog.times_applied + 1,
                            "last_applied_at": _now(),
                        },
                    )
                )
                await session.execute(stmt)
    except Exception as exc:
        logger.debug("upsert_tool_fix failed: %s", exc)


# ---------------------------------------------------------------------------
# RAG Retrievals
# ---------------------------------------------------------------------------

async def record_rag_retrieval(
    span_id: Optional[uuid.UUID],
    query: str,
    filter_type: Optional[str],
    k_requested: int,
    results: list,
    duration_ms: int,
) -> None:
    if not _enabled or span_id is None:
        return
    # Store only snippet of each result text to keep JSONB size reasonable
    compact = [
        {
            "id": r.get("id", ""),
            "source": r.get("source", ""),
            "doc_type": r.get("doc_type", ""),
            "relevance": r.get("relevance", 0),
            "text_snippet": r.get("text", "")[:200],
        }
        for r in results
    ]
    row = RagRetrieval(
        span_id=span_id,
        query=query,
        filter_type=filter_type,
        k_requested=k_requested,
        results_count=len(results),
        results=compact,
        duration_ms=duration_ms,
    )
    await _persist(row)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

async def record_event(
    source: str,
    event_type: Optional[str],
    topic: Optional[str],
    payload: dict,
    metadata: dict,
    route_matched: Optional[str] = None,
    trace_id: Optional[uuid.UUID] = None,
) -> Optional[uuid.UUID]:
    """Persist an incoming event. Returns the event UUID for later update."""
    if not _enabled:
        return None
    eid = uuid.uuid4()
    row = EventRecord(
        id=eid,
        trace_id=trace_id,
        source=source,
        event_type=event_type,
        topic=topic,
        payload=payload,
        metadata_=metadata,
        route_matched=route_matched,
    )
    await _persist(row)
    return eid


async def complete_event(
    event_id: Optional[uuid.UUID],
    trace_id: Optional[uuid.UUID],
    processing_ms: int,
) -> None:
    if not _enabled or event_id is None:
        return
    from sqlalchemy import update as sa_update
    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                await session.execute(
                    sa_update(EventRecord)
                    .where(EventRecord.id == event_id)
                    .values(trace_id=trace_id, processed_at=_now(), processing_ms=processing_ms)
                )
    except Exception as exc:
        logger.warning("complete_event failed: %s", exc)
