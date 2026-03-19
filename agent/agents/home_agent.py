"""
Home Agent — controls physical devices: blinds/shutters and the front door intercom.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from agents.base_agent import BaseAgent

if TYPE_CHECKING:
    from context import AgentContext

HOME_TOOLS = ["set_blinds_state", "set_all_blinds_state", "fermax_open_door"]
HOME_CAPABILITIES = ["home_automation", "blinds", "door_control"]

HOME_PROMPT = """You are the Home Agent for Open-Claudio.
You control physical devices: blinds/shutters (persianas) and the front door intercom.
Use the provided tools precisely. Stay within your domain."""


def make_home_agent(ctx: AgentContext) -> BaseAgent:
    """Factory that creates a pre-configured Home Agent."""
    return BaseAgent("home", HOME_TOOLS, ctx, HOME_PROMPT, HOME_CAPABILITIES)
