from fastapi import APIRouter, Query
from sqlalchemy import select, desc
from db.connection import AsyncSessionFactory
from db.models import RagDocument, RagRetrieval

router = APIRouter(prefix="/api/rag", tags=["rag"])


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
