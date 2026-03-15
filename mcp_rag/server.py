"""
MCP RAG Server — exposes the knowledge base as four FastMCP tools:

  rag_search(query, k, filter_type)               → hybrid semantic + keyword retrieval
  rag_ingest(content, source, doc_type, tags)     → add / update a document from text
  rag_ingest_file(file_path, doc_type, tags)      → add / update from a file in /docs
  rag_delete_source(source)                       → delete all chunks for a source
  rag_list_sources()                              → list all indexed sources

Supported file formats for rag_ingest_file: .txt, .md, .markdown, .pdf
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

from ingestion import load_file
from rag_engine import RAGEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_rag")

engine = RAGEngine()
mcp = FastMCP("rag")


@mcp.tool()
def rag_search(query: str, k: int = 5, filter_type: Optional[str] = None) -> str:
    """Search the knowledge base using hybrid semantic + keyword retrieval.

    Combines dense vector similarity (ChromaDB / cosine) with sparse BM25 keyword
    matching. Results are merged via Reciprocal Rank Fusion for maximum relevance.

    Args:
        query: Natural-language question or search terms.
        k: Maximum number of results to return (default: 5).
        filter_type: Optional doc_type filter — e.g. "manual", "config",
                     "log", "preference", "conversation". Pass null for no filter.

    Returns:
        JSON array of result objects, each containing:
        {id, text, source, doc_type, tags, relevance (0-1)}
    """
    logger.info("rag_search query='%s' k=%d filter=%s", query, k, filter_type)
    results = engine.search(query, k=k, filter_type=filter_type)
    return json.dumps(results, ensure_ascii=False)


@mcp.tool()
def rag_ingest(content: str, source: str, doc_type: str, tags: str = "") -> str:
    """Add or update a document in the knowledge base.

    The document is split into overlapping chunks, embedded, and stored in
    ChromaDB. Re-ingesting the same source replaces all previous chunks for
    that source (upsert behaviour).

    Args:
        content: Full text of the document to index.
        source: Unique identifier for this document (e.g. "blinds_manual",
                "user_preferences", "fermax_api_docs").
        doc_type: Category for filtering. Use one of: "manual", "config",
                  "log", "preference", "conversation", "other".
        tags: Optional comma-separated labels, e.g. "zwave,blinds,salon".

    Returns:
        JSON object: {status, source, doc_type, chunks_ingested}
    """
    logger.info("rag_ingest source='%s' doc_type='%s'", source, doc_type)
    result = engine.ingest(content, source=source, doc_type=doc_type, tags=tags)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def rag_ingest_file(file_path: str, doc_type: str, tags: str = "", source: str = "") -> str:
    """Load a file from the /docs volume and ingest it into the knowledge base.

    Supports: .txt  (plain text)
              .md / .markdown  (Markdown — formatting stripped, text preserved)
              .pdf  (PDF — text extracted per page with [Page N] markers)

    The file is automatically parsed, chunked, embedded, and stored.
    Re-ingesting the same file replaces all previous chunks (upsert).

    Args:
        file_path: Path to the file inside the /docs directory.
                   Examples: "/docs/blinds_manual.pdf", "/docs/setup.md"
        doc_type: Category for filtering. Use one of: "manual", "config",
                  "log", "preference", "conversation", "other".
        tags: Optional comma-separated labels, e.g. "zwave,blinds,salon".
        source: Optional custom source identifier. Defaults to the filename.

    Returns:
        JSON object: {status, source, doc_type, format, chunks_ingested}
    """
    # Security: restrict to /docs directory
    try:
        abs_path = str(Path(file_path).resolve())
    except Exception as exc:
        return json.dumps({"status": "error", "message": f"Invalid path: {exc}"})

    if not abs_path.startswith("/docs"):
        return json.dumps(
            {"status": "error", "message": "Access denied: files must be inside /docs."}
        )

    logger.info("rag_ingest_file path='%s' doc_type='%s'", abs_path, doc_type)

    try:
        content, fmt = load_file(abs_path)
    except (FileNotFoundError, ValueError, ImportError) as exc:
        return json.dumps({"status": "error", "message": str(exc)})

    source_name = source or Path(abs_path).name
    combined_tags = f"{tags},{fmt}".strip(",") if tags else fmt

    result = engine.ingest(content, source=source_name, doc_type=doc_type, tags=combined_tags)
    result["format"] = fmt
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def rag_delete_source(source: str) -> str:
    """Delete all chunks of a document from the knowledge base.

    Use rag_list_sources first to confirm the exact source identifier.

    Args:
        source: The source identifier used when the document was ingested
                (e.g. "fermax_manual.pdf", "user_preferences").

    Returns:
        JSON object: {status, source, chunks_deleted}
        status is "ok" if deleted, "not_found" if the source didn't exist.
    """
    logger.info("rag_delete_source source='%s'", source)
    result = engine.delete_source(source)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def rag_list_sources() -> str:
    """List all documents currently indexed in the knowledge base.

    Returns:
        JSON array of source objects:
        {source, doc_type, tags, chunk_count, timestamp}
    """
    logger.info("rag_list_sources")
    sources = engine.list_sources()
    return json.dumps(sources, ensure_ascii=False)


if __name__ == "__main__":
    port = int(os.getenv("RAG_PORT", "8002"))
    logger.info("Starting RAG MCP Server on port %d ...", port)
    mcp.run(transport="sse", host="0.0.0.0", port=port)
