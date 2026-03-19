"""
Server Agent — handles file operations, HTTP requests, and server diagnostics.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from agents.base_agent import BaseAgent

if TYPE_CHECKING:
    from context import AgentContext

SERVER_TOOLS = ["read_file", "list_files", "http_get"]
SERVER_CAPABILITIES = ["server", "file_system", "http"]

SERVER_PROMPT = """You are the Server Agent for Open-Claudio.
You handle file operations, HTTP requests, and server diagnostics."""


def make_server_agent(ctx: AgentContext) -> BaseAgent:
    """Factory that creates a pre-configured Server Agent."""
    return BaseAgent("server", SERVER_TOOLS, ctx, SERVER_PROMPT, SERVER_CAPABILITIES)
