import os
import httpx
from fastapi import APIRouter, Query, UploadFile, File, Form, HTTPException
from sqlalchemy import select, desc
from db.connection import AsyncSessionFactory
from db.models import RagDocument, RagRetrieval

router = APIRouter(prefix="/api/rag", tags=["rag"])

RAG_REST_URL = os.getenv("RAG_REST_URL", "http://mcp_rag:8003")


# ── Live data from ChromaDB (via mcp_rag REST) ──────────────────────────────

@router.get("/sources")
async def list_sources_live():
    """Live list from ChromaDB (not the observability DB)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(f"{RAG_REST_URL}/sources")
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            raise HTTPException(502, f"RAG service unavailable: {exc}")


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    doc_type: str = Form("other"),
    tags: str = Form(""),
    source: str = Form(""),
):
    """Upload a file and ingest it into the knowledge base."""
    content = await file.read()
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            r = await client.post(
                f"{RAG_REST_URL}/ingest",
                files={"file": (file.filename, content, file.content_type or "application/octet-stream")},
                data={"doc_type": doc_type, "tags": tags, "source": source},
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, e.response.text)
        except Exception as exc:
            raise HTTPException(502, f"RAG service error: {exc}")


@router.delete("/sources/{source_name:path}")
async def delete_source(source_name: str):
    """Delete all chunks for a source from the knowledge base."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.delete(f"{RAG_REST_URL}/sources/{source_name}")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, e.response.text)
        except Exception as exc:
            raise HTTPException(502, f"RAG service error: {exc}")


# ── Observability data from PostgreSQL ──────────────────────────────────────

@router.get("/documents")
async def list_documents(include_deleted: bool = False):
    async with AsyncSessionFactory() as session:
        q = select(RagDocument).order_by(desc(RagDocument.ingested_at))
        if not include_deleted:
            q = q.where(RagDocument.deleted_at == None)
        result = await session.execute(q)
        docs = result.scalars().all()
        return [{
            "id": str(d.id),
            "source": d.source,
            "doc_type": d.doc_type,
            "format": d.format,
            "chunk_count": d.chunk_count,
            "word_count_approx": d.word_count_approx,
            "embedding_model": d.embedding_model,
            "ingested_at": d.ingested_at.isoformat() if d.ingested_at else None,
            "deleted_at": d.deleted_at.isoformat() if d.deleted_at else None,
        } for d in docs]


@router.get("/retrievals")
async def list_retrievals(limit: int = Query(50, le=200), offset: int = 0):
    async with AsyncSessionFactory() as session:
        q = select(RagRetrieval).order_by(desc(RagRetrieval.created_at)).limit(limit).offset(offset)
        result = await session.execute(q)
        retrievals = result.scalars().all()
        return [{
            "id": str(r.id),
            "span_id": str(r.span_id),
            "query": r.query,
            "results_count": r.results_count,
            "duration_ms": r.duration_ms,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in retrievals]
