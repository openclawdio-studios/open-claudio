"""
Standalone FastAPI REST API for the RAG knowledge base.
Runs on port RAG_REST_PORT (default 8003) alongside the MCP server (8002).

Endpoints:
  GET  /sources                → list all indexed sources
  POST /ingest                 → upload a file and ingest it
  DELETE /sources/{source}     → delete all chunks for a source
  GET  /health                 → health check
"""

import logging
import os
import tempfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from ingestion import load_file
from rag_engine import RAGEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag_rest")

app = FastAPI(title="RAG REST API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = RAGEngine()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/sources")
def list_sources():
    """List all documents currently indexed in the knowledge base."""
    return engine.list_sources()


@app.post("/ingest")
async def ingest_file(
    file: UploadFile = File(...),
    doc_type: str = Form("other"),
    tags: str = Form(""),
    source: str = Form(""),
):
    """Upload a file (.txt, .md, .pdf) and ingest it into the knowledge base."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".txt", ".md", ".markdown", ".pdf"}:
        raise HTTPException(400, f"Unsupported file type: {suffix!r}. Use .txt, .md, or .pdf")

    content_bytes = await file.read()

    # Write to a temp file so load_file() can parse it
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content_bytes)
        tmp_path = tmp.name

    try:
        text, fmt = load_file(tmp_path)
    except (FileNotFoundError, ValueError, ImportError) as exc:
        raise HTTPException(422, str(exc))
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    source_name = source or file.filename or "upload"
    combined_tags = f"{tags},{fmt}".strip(",") if tags else fmt

    result = engine.ingest(text, source=source_name, doc_type=doc_type, tags=combined_tags)
    result["format"] = fmt
    return result


@app.delete("/sources/{source_name:path}")
def delete_source(source_name: str):
    """Delete all chunks for a given source from the knowledge base."""
    result = engine.delete_source(source_name)
    if result.get("status") == "not_found":
        raise HTTPException(404, f"Source not found: {source_name!r}")
    return result


if __name__ == "__main__":
    port = int(os.getenv("RAG_REST_PORT", "8003"))
    logger.info("Starting RAG REST API on port %d ...", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
