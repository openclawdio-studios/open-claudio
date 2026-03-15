"""
Intercom Agent — queries information about the Fermax video intercom.
"""

from agents.base_agent import BaseAgent
from mcp_client import MultiMCPClient
from openai import AsyncOpenAI

INTERCOM_TOOLS = ["get_fermax_user_info", "get_fermax_device_info", "get_fermax_history"]

INTERCOM_PROMPT = """You are the Intercom Agent for Open-Claudio.
You query information about the Fermax video intercom: user info, device status, call history."""


def make_intercom_agent(
    mcp_client: MultiMCPClient,
    memory: dict,
    llm_client: AsyncOpenAI,
    model: str,
) -> BaseAgent:
    """Factory that creates a pre-configured Intercom Agent."""
    return BaseAgent(
        "intercom", INTERCOM_TOOLS, mcp_client, memory, llm_client, model, INTERCOM_PROMPT
    )
