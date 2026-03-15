from fastapi import APIRouter
from sqlalchemy import text
from db.connection import AsyncSessionFactory

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/daily-tokens")
async def daily_tokens():
    async with AsyncSessionFactory() as session:
        result = await session.execute(text("SELECT * FROM v_daily_token_usage ORDER BY day DESC LIMIT 30"))
        rows = result.mappings().all()
        return [dict(r) for r in rows]


@router.get("/tool-success-rates")
async def tool_success_rates():
    async with AsyncSessionFactory() as session:
        result = await session.execute(text("SELECT * FROM v_tool_success_rates ORDER BY total_calls DESC"))
        rows = result.mappings().all()
        return [dict(r) for r in rows]


@router.get("/span-latency")
async def span_latency():
    async with AsyncSessionFactory() as session:
        result = await session.execute(text("SELECT * FROM v_span_latency ORDER BY p95_ms DESC LIMIT 20"))
        rows = result.mappings().all()
        return [dict(r) for r in rows]


@router.get("/rag-quality")
async def rag_quality():
    async with AsyncSessionFactory() as session:
        result = await session.execute(text("SELECT * FROM v_rag_search_quality ORDER BY day DESC LIMIT 30"))
        rows = result.mappings().all()
        return [dict(r) for r in rows]


@router.get("/summary")
async def summary():
    async with AsyncSessionFactory() as session:
        r = await session.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM traces) AS total_traces,
                (SELECT COUNT(*) FROM traces WHERE status='ok') AS successful_traces,
                (SELECT COALESCE(SUM(tokens_prompt_total + tokens_completion_total), 0) FROM traces) AS total_tokens,
                (SELECT COUNT(*) FROM tool_calls) AS total_tool_calls,
                (SELECT COUNT(*) FROM tool_calls WHERE success = false) AS failed_tool_calls,
                (SELECT COUNT(*) FROM rag_documents WHERE deleted_at IS NULL) AS rag_documents
        """))
        row = r.mappings().first()
        return dict(row) if row else {}
