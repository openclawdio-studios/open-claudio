"""
Utility Agent — handles time queries and generic HTTP lookups.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from agents.base_agent import BaseAgent

if TYPE_CHECKING:
    from context import AgentContext

UTILITY_TOOLS = ["get_time", "http_get"]
UTILITY_CAPABILITIES = ["utility", "time", "http"]

UTILITY_PROMPT = """You are the Utility Agent for Open-Claudio.
You handle time queries and generic HTTP lookups."""


def make_utility_agent(ctx: AgentContext) -> BaseAgent:
    """Factory that creates a pre-configured Utility Agent."""
    return BaseAgent("utility", UTILITY_TOOLS, ctx, UTILITY_PROMPT, UTILITY_CAPABILITIES)
