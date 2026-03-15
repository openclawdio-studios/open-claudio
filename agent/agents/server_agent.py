"""
Server Agent — handles file operations, HTTP requests, and server diagnostics.
"""

from agents.base_agent import BaseAgent
from mcp_client import MultiMCPClient
from openai import AsyncOpenAI

SERVER_TOOLS = ["read_file", "list_files", "http_get"]

SERVER_PROMPT = """You are the Server Agent for Open-Claudio.
You handle file operations, HTTP requests, and server diagnostics."""


def make_server_agent(
    mcp_client: MultiMCPClient,
    memory: dict,
    llm_client: AsyncOpenAI,
    model: str,
) -> BaseAgent:
    """Factory that creates a pre-configured Server Agent."""
    return BaseAgent("server", SERVER_TOOLS, mcp_client, memory, llm_client, model, SERVER_PROMPT)
