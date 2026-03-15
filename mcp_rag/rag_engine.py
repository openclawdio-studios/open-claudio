"""
RAGEngine — hybrid retrieval using ChromaDB (dense) + BM25 (sparse),
merged via Reciprocal Rank Fusion (RRF).

Embedding model: nomic-ai/nomic-embed-text-v1.5
  - Requires task prefixes:
      "search_document: <text>"  → used when indexing chunks
      "search_query: <text>"     → used when querying
  - 768-dim vectors, state-of-the-art local model (MTEB ~62)
  - trust_remote_code=True required

Design:
- ChromaDB handles vector storage and cosine-similarity search.
- BM25 index is kept in-memory (rebuilt from ChromaDB on startup and after each ingest).
- RRF merges both ranked lists into a single result set.
- Metadata (source, doc_type, tags, timestamp) is stored alongside every chunk.
"""

import logging
import os
from datetime import datetime
from typing import Optional

import chromadb
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from ingestion import chunk_text

logger = logging.getLogger("rag_engine")

_EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5")
_DATA_DIR = os.getenv("RAG_DATA_DIR", "/data")


class RAGEngine:
    """
    Hybrid RAG engine with persistent ChromaDB storage.

    Parameters
    ----------
    data_dir : str
        Directory where ChromaDB persists its data.
    """

    def __init__(self, data_dir: str = _DATA_DIR):
        os.makedirs(data_dir, exist_ok=True)

        logger.info("Initialising ChromaDB at %s ...", data_dir)
        self._chroma = chromadb.PersistentClient(path=data_dir)
        self._collection = self._chroma.get_or_create_collection(
            "knowledge",
            metadata={"hnsw:space": "cosine"},
        )

        logger.info("Loading embedding model: %s ...", _EMBED_MODEL)
        self._model = SentenceTransformer(_EMBED_MODEL, trust_remote_code=True)

        # In-memory BM25 corpus — mirrors ChromaDB, rebuilt on startup and ingest
        self._bm25: Optional[BM25Okapi] = None
        self._corpus_ids: list[str] = []
        self._corpus_texts: list[str] = []
        self._corpus_meta: list[dict] = []
        self._rebuild_bm25()

        logger.info("RAGEngine ready. Corpus: %d chunks.", len(self._corpus_ids))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rebuild_bm25(self) -> None:
        """Reload all documents from ChromaDB and rebuild the BM25 index."""
        try:
            result = self._collection.get(include=["documents", "metadatas"])
            self._corpus_ids = result.get("ids", []) or []
            self._corpus_texts = result.get("documents", []) or []
            self._corpus_meta = result.get("metadatas", []) or []

            if self._corpus_texts:
                tokenized = [t.lower().split() for t in self._corpus_texts]
                self._bm25 = BM25Okapi(tokenized)
            else:
                self._bm25 = None
        except Exception as exc:
            logger.error("BM25 rebuild failed: %s", exc)
            self._bm25 = None

    @staticmethod
    def _rrf_merge(dense_ids: list[str], sparse_ids: list[str], k: int = 60) -> list[str]:
        """
        Reciprocal Rank Fusion.
        score(d) = Σ 1 / (k + rank(d))  across both ranked lists.
        """
        scores: dict[str, float] = {}
        for rank, doc_id in enumerate(dense_ids):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
        for rank, doc_id in enumerate(sparse_ids):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
        return sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        k: int = 5,
        filter_type: Optional[str] = None,
    ) -> list[dict]:
        """
        Hybrid search: dense cosine similarity + BM25, merged via RRF.

        Parameters
        ----------
        query : str
            Natural-language question or keywords.
        k : int
            Number of results to return.
        filter_type : str | None
            If given, restrict results to chunks with this doc_type.

        Returns
        -------
        list[dict]
            Each dict: {id, text, source, doc_type, tags, relevance}
        """
        total = self._collection.count()
        if total == 0:
            return []

        fetch_k = min(k * 3, total)
        # nomic-embed-text-v1.5 requires a task prefix for queries
        query_emb = self._model.encode(
            f"search_query: {query}", normalize_embeddings=True
        ).tolist()
        where = {"doc_type": filter_type} if filter_type else None

        # 1. Dense retrieval (ChromaDB)
        dense = self._collection.query(
            query_embeddings=[query_emb],
            n_results=fetch_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        dense_ids: list[str] = dense["ids"][0] if dense["ids"] else []
        # Build lookup dict for fast access
        dense_data: dict[str, dict] = {}
        if dense_ids:
            for doc_id, doc, meta, dist in zip(
                dense["ids"][0],
                dense["documents"][0],
                dense["metadatas"][0],
                dense["distances"][0],
            ):
                dense_data[doc_id] = {"text": doc, "metadata": meta, "distance": dist}

        # 2. Sparse retrieval (BM25)
        sparse_ids: list[str] = []
        if self._bm25 and self._corpus_ids:
            bm25_scores = self._bm25.get_scores(query.lower().split())
            ranked_indices = sorted(
                range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True
            )
            for idx in ranked_indices:
                if bm25_scores[idx] <= 0 or len(sparse_ids) >= fetch_k:
                    break
                doc_id = self._corpus_ids[idx]
                # Respect filter_type using in-memory metadata
                if filter_type:
                    meta = self._corpus_meta[idx] if idx < len(self._corpus_meta) else {}
                    if meta.get("doc_type") != filter_type:
                        continue
                sparse_ids.append(doc_id)

        # 3. Merge via RRF
        merged_ids = self._rrf_merge(dense_ids, sparse_ids)[:k]

        # 4. Build output — prefer data already in dense_data, else fetch from ChromaDB
        results: list[dict] = []
        for doc_id in merged_ids:
            if doc_id in dense_data:
                entry = dense_data[doc_id]
                meta = entry["metadata"]
                results.append(
                    {
                        "id": doc_id,
                        "text": entry["text"],
                        "source": meta.get("source", ""),
                        "doc_type": meta.get("doc_type", ""),
                        "tags": meta.get("tags", ""),
                        "relevance": round(1.0 - entry["distance"], 3),
                    }
                )
            else:
                # BM25-only hit — fetch full document
                try:
                    r = self._collection.get(ids=[doc_id], include=["documents", "metadatas"])
                    if r["documents"]:
                        meta = r["metadatas"][0] if r["metadatas"] else {}
                        results.append(
                            {
                                "id": doc_id,
                                "text": r["documents"][0],
                                "source": meta.get("source", ""),
                                "doc_type": meta.get("doc_type", ""),
                                "tags": meta.get("tags", ""),
                                "relevance": 0.5,
                            }
                        )
                except Exception as exc:
                    logger.warning("Failed to fetch BM25-only doc %s: %s", doc_id, exc)

        return results

    def ingest(
        self,
        content: str,
        source: str,
        doc_type: str,
        tags: str = "",
    ) -> dict:
        """
        Chunk, embed, and store a document in ChromaDB.
        Re-ingesting the same source replaces existing chunks for that source.

        Parameters
        ----------
        content : str
            Raw document text.
        source : str
            Unique identifier (filename, URL, label).
        doc_type : str
            Category: "manual", "config", "log", "preference", "conversation", etc.
        tags : str
            Comma-separated labels for filtering.

        Returns
        -------
        dict
            Ingestion summary: {status, source, chunks_ingested, doc_type}
        """
        chunks = chunk_text(content)
        if not chunks:
            return {"status": "error", "message": "Empty content — nothing ingested."}

        timestamp = datetime.now().isoformat()

        # Delete existing chunks for this source (upsert behaviour)
        try:
            existing = self._collection.get(where={"source": source})
            if existing["ids"]:
                self._collection.delete(ids=existing["ids"])
                logger.info("Deleted %d existing chunks for source '%s'.", len(existing["ids"]), source)
        except Exception as exc:
            logger.warning("Could not delete existing chunks for '%s': %s", source, exc)

        ids = []
        embeddings = []
        metadatas = []

        for i, chunk in enumerate(chunks):
            ids.append(f"{source}::{i}")
            # nomic-embed-text-v1.5 requires "search_document:" prefix for indexed text
            embeddings.append(
                self._model.encode(
                    f"search_document: {chunk}", normalize_embeddings=True
                ).tolist()
            )
            metadatas.append(
                {
                    "source": source,
                    "doc_type": doc_type,
                    "tags": tags,
                    "chunk_index": i,
                    "timestamp": timestamp,
                }
            )

        self._collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
        )

        self._rebuild_bm25()

        logger.info("Ingested %d chunks from source '%s' (type=%s).", len(chunks), source, doc_type)
        return {
            "status": "ok",
            "source": source,
            "doc_type": doc_type,
            "chunks_ingested": len(chunks),
        }

    def delete_source(self, source: str) -> dict:
        """
        Delete all chunks belonging to a given source.

        Parameters
        ----------
        source : str
            The source identifier used during ingestion.

        Returns
        -------
        dict
            {status, source, chunks_deleted}
        """
        try:
            result = self._collection.get(where={"source": source})
            ids = result.get("ids", [])
            if not ids:
                return {"status": "not_found", "source": source, "chunks_deleted": 0}

            self._collection.delete(ids=ids)
            self._rebuild_bm25()

            logger.info("Deleted %d chunks for source '%s'.", len(ids), source)
            return {"status": "ok", "source": source, "chunks_deleted": len(ids)}
        except Exception as exc:
            logger.error("delete_source failed for '%s': %s", source, exc)
            return {"status": "error", "source": source, "message": str(exc)}

    def list_sources(self) -> list[dict]:
        """
        Return a deduplicated list of indexed sources with chunk counts.

        Returns
        -------
        list[dict]
            Each dict: {source, doc_type, tags, chunk_count, timestamp}
        """
        try:
            result = self._collection.get(include=["metadatas"])
            metadatas = result.get("metadatas", []) or []

            sources: dict[str, dict] = {}
            for meta in metadatas:
                src = meta.get("source", "unknown")
                if src not in sources:
                    sources[src] = {
                        "source": src,
                        "doc_type": meta.get("doc_type", ""),
                        "tags": meta.get("tags", ""),
                        "chunk_count": 0,
                        "timestamp": meta.get("timestamp", ""),
                    }
                sources[src]["chunk_count"] += 1

            return list(sources.values())
        except Exception as exc:
            logger.error("list_sources failed: %s", exc)
            return []
