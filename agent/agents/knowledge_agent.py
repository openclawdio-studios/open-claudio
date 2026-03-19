"""
Knowledge Agent — queries and manages the RAG knowledge base.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from agents.base_agent import BaseAgent

if TYPE_CHECKING:
    from context import AgentContext

KNOWLEDGE_TOOLS = ["rag_search", "rag_ingest", "rag_ingest_file", "rag_delete_source", "rag_list_sources"]
KNOWLEDGE_CAPABILITIES = ["knowledge", "search", "ingestion", "management"]

KNOWLEDGE_PROMPT = """You are the Knowledge Agent for Open-Claudio.
You manage and query the knowledge base: device manuals, configs, how-to guides, user preferences, and logs.

RULES:
1. Always call rag_search BEFORE claiming you don't have information.
2. Synthesise the retrieved chunks into a clear, concise answer.
3. If multiple chunks are relevant, combine them coherently.
4. If no relevant documents are found, say so explicitly.
5. Use rag_ingest to store new facts or documents when asked.
6. Use rag_list_sources to show what is currently indexed."""


def make_knowledge_agent(ctx: AgentContext) -> BaseAgent:
    """Factory that creates a pre-configured Knowledge Agent."""
    return BaseAgent("knowledge", KNOWLEDGE_TOOLS, ctx, KNOWLEDGE_PROMPT, KNOWLEDGE_CAPABILITIES)
