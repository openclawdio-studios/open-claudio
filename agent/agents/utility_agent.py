"""
Utility Agent — handles time queries and generic HTTP lookups.
"""

from agents.base_agent import BaseAgent
from mcp_client import MultiMCPClient
from openai import AsyncOpenAI

UTILITY_TOOLS = ["get_time", "http_get"]

UTILITY_PROMPT = """You are the Utility Agent for Open-Claudio.
You handle time queries and generic HTTP lookups."""


def make_utility_agent(
    mcp_client: MultiMCPClient,
    memory: dict,
    llm_client: AsyncOpenAI,
    model: str,
) -> BaseAgent:
    """Factory that creates a pre-configured Utility Agent."""
    return BaseAgent(
        "utility", UTILITY_TOOLS, mcp_client, memory, llm_client, model, UTILITY_PROMPT
    )
