from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy import text
from db.connection import AsyncSessionFactory
from db.models import User
from auth import get_optional_user

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _uid(viewer: Optional[User]) -> Optional[str]:
    """Return user UUID string if filtering is needed, else None."""
    if viewer and not viewer.is_admin:
        return str(viewer.id)
    return None


@router.get("/daily-tokens")
async def daily_tokens(viewer: Optional[User] = Depends(get_optional_user)):
    uid = _uid(viewer)
    async with AsyncSessionFactory() as session:
        if uid:
            result = await session.execute(text("""
                SELECT
                    date_trunc('day', lc.created_at) AS day,
                    lc.model,
                    COUNT(*) AS llm_calls,
                    SUM(lc.tokens_prompt) AS tokens_prompt,
                    SUM(lc.tokens_completion) AS tokens_completion,
                    SUM(lc.tokens_prompt + lc.tokens_completion) AS tokens_total,
                    AVG(lc.duration_ms) AS avg_latency_ms
                FROM llm_calls lc
                JOIN spans s ON lc.span_id = s.id
                JOIN traces t ON s.trace_id = t.id
                WHERE t.user_id = CAST(:uid AS uuid)
                GROUP BY 1, 2
                ORDER BY 1 DESC, tokens_total DESC
                LIMIT 30
            """), {"uid": uid})
        else:
            result = await session.execute(
                text("SELECT * FROM v_daily_token_usage ORDER BY day DESC LIMIT 30")
            )
        return [dict(r) for r in result.mappings().all()]


@router.get("/tool-success-rates")
async def tool_success_rates(viewer: Optional[User] = Depends(get_optional_user)):
    uid = _uid(viewer)
    async with AsyncSessionFactory() as session:
        if uid:
            result = await session.execute(text("""
                SELECT
                    tc.tool_name, tc.tool_source,
                    COUNT(*) AS total_calls,
                    SUM(CASE WHEN tc.success THEN 1 ELSE 0 END) AS successful,
                    ROUND(100.0 * SUM(CASE WHEN tc.success THEN 1 ELSE 0 END) / COUNT(*), 2) AS success_rate_pct,
                    AVG(tc.retries) AS avg_retries,
                    AVG(tc.duration_ms) AS avg_duration_ms,
                    SUM(CASE WHEN tc.healing_strategy IS NOT NULL THEN 1 ELSE 0 END) AS healed_calls
                FROM tool_calls tc
                JOIN spans s ON tc.span_id = s.id
                JOIN traces t ON s.trace_id = t.id
                WHERE t.user_id = CAST(:uid AS uuid)
                GROUP BY 1, 2
                ORDER BY total_calls DESC
            """), {"uid": uid})
        else:
            result = await session.execute(
                text("SELECT * FROM v_tool_success_rates ORDER BY total_calls DESC")
            )
        return [dict(r) for r in result.mappings().all()]


@router.get("/span-latency")
async def span_latency(viewer: Optional[User] = Depends(get_optional_user)):
    uid = _uid(viewer)
    async with AsyncSessionFactory() as session:
        if uid:
            result = await session.execute(text("""
                SELECT
                    s.span_type, s.name,
                    COUNT(*) AS executions,
                    AVG(s.duration_ms) AS avg_ms,
                    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY s.duration_ms) AS p50_ms,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY s.duration_ms) AS p95_ms,
                    MAX(s.duration_ms) AS max_ms,
                    SUM(CASE WHEN s.status = 'error' THEN 1 ELSE 0 END) AS errors
                FROM spans s
                JOIN traces t ON s.trace_id = t.id
                WHERE s.duration_ms IS NOT NULL
                  AND t.user_id = CAST(:uid AS uuid)
                GROUP BY 1, 2
                ORDER BY avg_ms DESC
                LIMIT 20
            """), {"uid": uid})
        else:
            result = await session.execute(
                text("SELECT * FROM v_span_latency ORDER BY p95_ms DESC LIMIT 20")
            )
        return [dict(r) for r in result.mappings().all()]


@router.get("/rag-quality")
async def rag_quality():
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            text("SELECT * FROM v_rag_search_quality ORDER BY created_at DESC LIMIT 30")
        )
        return [dict(r) for r in result.mappings().all()]


@router.get("/summary")
async def summary(viewer: Optional[User] = Depends(get_optional_user)):
    uid = _uid(viewer)
    async with AsyncSessionFactory() as session:
        if uid:
            r = await session.execute(text("""
                SELECT
                    (SELECT COUNT(*) FROM traces WHERE user_id = CAST(:uid AS uuid)) AS total_traces,
                    (SELECT COUNT(*) FROM traces WHERE status='success' AND user_id = CAST(:uid AS uuid)) AS successful_traces,
                    (SELECT COALESCE(SUM(tokens_prompt_total + tokens_completion_total), 0)
                       FROM traces WHERE user_id = CAST(:uid AS uuid)) AS total_tokens,
                    (SELECT COUNT(*) FROM tool_calls tc
                       JOIN spans s ON tc.span_id = s.id
                       JOIN traces t ON s.trace_id = t.id
                       WHERE t.user_id = CAST(:uid AS uuid)) AS total_tool_calls,
                    (SELECT COUNT(*) FROM tool_calls tc
                       JOIN spans s ON tc.span_id = s.id
                       JOIN traces t ON s.trace_id = t.id
                       WHERE t.user_id = CAST(:uid AS uuid) AND tc.success = false) AS failed_tool_calls,
                    (SELECT COUNT(*) FROM rag_documents WHERE deleted_at IS NULL) AS rag_documents
            """), {"uid": uid})
        else:
            r = await session.execute(text("""
                SELECT
                    (SELECT COUNT(*) FROM traces) AS total_traces,
                    (SELECT COUNT(*) FROM traces WHERE status='success') AS successful_traces,
                    (SELECT COALESCE(SUM(tokens_prompt_total + tokens_completion_total), 0) FROM traces) AS total_tokens,
                    (SELECT COUNT(*) FROM tool_calls) AS total_tool_calls,
                    (SELECT COUNT(*) FROM tool_calls WHERE success = false) AS failed_tool_calls,
                    (SELECT COUNT(*) FROM rag_documents WHERE deleted_at IS NULL) AS rag_documents
            """))
        row = r.mappings().first()
        result = dict(row) if row else {}
        # Include context so the frontend knows whose data is shown
        result["_viewer"] = viewer.username if viewer else None
        result["_is_admin"] = viewer.is_admin if viewer else True
        return result
