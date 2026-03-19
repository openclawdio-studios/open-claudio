"""
AgentContext — unified context object shared across all agents and the executor.

Contains two categories of data:
  - Services  : live objects (mcp_client, llm_client, model, executor) — not persisted
  - Scratchpad: stateful data (memory, history) — serialised to memory.json between sessions

All agents and the executor receive a single AgentContext instance so there is one
source of truth for both services and state.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from executor import Executor
    from mcp_client import MultiMCPClient
    from openai import AsyncOpenAI
    from tools_registry import DynamicToolRegistry

logger = logging.getLogger("AgentContext")

_MEMORY_PATH = "memory.json"


@dataclass
class AgentContext:
    """
    Single context object passed to every agent, planner, and executor.

    Parameters (services — not persisted)
    --------------------------------------
    mcp_client : MultiMCPClient
    llm_client : AsyncOpenAI
    model      : str
    executor   : Executor

    Parameters (scratchpad — persisted to memory.json)
    ---------------------------------------------------
    memory  : per-agent namespaced state dict (tool_fixes, tool_metrics, domain data)
    history : cross-agent conversation history (populated by future phases)
    events  : recent processed events (populated by future phases)
    """

    # Services
    mcp_client: MultiMCPClient
    llm_client: AsyncOpenAI
    model: str
    executor: Optional[Executor]          # set after construction to avoid circular init
    registry: Optional[DynamicToolRegistry] = field(default=None)  # set after construction

    # Scratchpad
    memory: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict] = field(default_factory=list)
    events: List[Any] = field(default_factory=list)

    # Transient — last successful tool call this session (for correction detection)
    last_tool_call: Optional[Dict[str, Any]] = field(default=None)

    # ------------------------------------------------------------------
    # Per-agent memory accessor
    # ------------------------------------------------------------------

    def agent_memory(self, name: str) -> Dict:
        """Return (and lazily create) the per-agent sub-dict of memory."""
        return self.memory.setdefault(name, {})

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str = _MEMORY_PATH) -> None:
        """Persist scratchpad (memory + history) to disk. Services are not saved."""
        try:
            with open(path, "w") as f:
                json.dump({"memory": self.memory, "history": self.history}, f, indent=2)
            logger.debug(f"AgentContext scratchpad saved to {path}")
        except Exception as e:
            logger.error(f"AgentContext.save() failed: {e}")

    @staticmethod
    def load_scratchpad(path: str = _MEMORY_PATH) -> Dict[str, Any]:
        """
        Load persisted scratchpad from disk.

        Returns a dict with keys ``memory`` and ``history``.
        Handles both the new format and the old flat-dict format (pre-Phase 2).
        """
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, dict) and "memory" in data:
                # New format: {"memory": {...}, "history": [...]}
                return {"memory": data["memory"], "history": data.get("history", [])}
            else:
                # Old format: the entire JSON was the memory dict
                logger.info("Migrating memory.json from old flat format to new format.")
                return {"memory": data, "history": []}
        except FileNotFoundError:
            return {"memory": {}, "history": []}
        except Exception as e:
            logger.warning(f"AgentContext.load_scratchpad() failed ({e}), starting fresh.")
            return {"memory": {}, "history": []}
