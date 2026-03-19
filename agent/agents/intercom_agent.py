"""
Intercom Agent — queries information about the Fermax video intercom.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from agents.base_agent import BaseAgent

if TYPE_CHECKING:
    from context import AgentContext

INTERCOM_TOOLS = ["get_fermax_user_info", "get_fermax_device_info", "get_fermax_history"]
INTERCOM_CAPABILITIES = ["intercom", "account", "device", "history"]

INTERCOM_PROMPT = """You are the Intercom Agent for Open-Claudio.
You query information about the Fermax video intercom: user info, device status, call history."""


def make_intercom_agent(ctx: AgentContext) -> BaseAgent:
    """Factory that creates a pre-configured Intercom Agent."""
    return BaseAgent("intercom", INTERCOM_TOOLS, ctx, INTERCOM_PROMPT, INTERCOM_CAPABILITIES)
