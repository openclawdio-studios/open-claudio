"""
Home Agent — controls physical devices: blinds/shutters and the front door intercom.
"""

from agents.base_agent import BaseAgent
from mcp_client import MultiMCPClient
from openai import AsyncOpenAI

HOME_TOOLS = ["set_blinds_state", "set_all_blinds_state", "fermax_open_door"]

HOME_PROMPT = """You are the Home Agent for Open-Claudio.
You control physical devices: blinds/shutters (persianas) and the front door intercom.
Use the provided tools precisely. Stay within your domain."""


def make_home_agent(
    mcp_client: MultiMCPClient,
    memory: dict,
    llm_client: AsyncOpenAI,
    model: str,
) -> BaseAgent:
    """Factory that creates a pre-configured Home Agent."""
    return BaseAgent("home", HOME_TOOLS, mcp_client, memory, llm_client, model, HOME_PROMPT)
