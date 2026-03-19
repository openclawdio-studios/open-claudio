"""
DynamicToolRegistry — manages the lifecycle of user-created and auto-detected tools.

Tool lifecycle:
  candidate  → auto-detected pattern, not yet available to agents
  validated  → user-explicitly created (high confidence), immediately available
  production → candidate promoted after sustained successful use

Persistence: each tool is stored as a JSON file in tools/generated/.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("DynamicToolRegistry")

TOOLS_DIR = "tools/generated"
PROMOTION_MIN_CALLS = 4   # must be > 3 (per design)
PROMOTION_SUCCESS_RATE = 0.9


# ---------------------------------------------------------------------------
# DynamicTool
# ---------------------------------------------------------------------------

@dataclass
class DynamicTool:
    """
    A persisted tool created at runtime by the user or auto-detected by the agent.

    The implementation is stored as a declarative list of steps (existing tool calls),
    not as arbitrary Python code — this keeps execution safe and inspectable.

    Parameters
    ----------
    name        : snake_case tool name
    description : human-readable description shown to the LLM
    capabilities: capability tags (same taxonomy as TOOL_CAPABILITIES)
    origin      : "user" (explicit) or "auto" (pattern-detected)
    status      : "candidate" | "validated" | "production"
    confidence  : 0.0–1.0 (user-created = 1.0, auto-detected starts lower)
    version     : semver string, starts at "1.0"
    usage_count : how many times the tool has been called
    success_rate: rolling average success rate (None until first call)
    schema      : OpenAI parameter schema for this tool
    steps       : ordered list of {tool: str, args: dict} to execute
    """

    name: str
    description: str
    capabilities: List[str]
    origin: str
    status: str
    confidence: float
    version: str
    usage_count: int
    success_rate: Optional[float]
    schema: dict
    steps: List[dict]

    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Available to agents = validated or production."""
        return self.status in ("validated", "production")

    def record_call(self, success: bool) -> None:
        """Update rolling success_rate and usage_count."""
        self.usage_count += 1
        outcome = 1.0 if success else 0.0
        if self.success_rate is None:
            self.success_rate = outcome
        else:
            # Rolling average weighted by call count
            self.success_rate = (
                self.success_rate * (self.usage_count - 1) + outcome
            ) / self.usage_count

    def should_promote(self) -> bool:
        """Return True if this candidate is ready to become production."""
        return (
            self.status == "candidate"
            and self.usage_count > PROMOTION_MIN_CALLS
            and self.success_rate is not None
            and self.success_rate >= PROMOTION_SUCCESS_RATE
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": self.capabilities,
            "origin": self.origin,
            "status": self.status,
            "confidence": self.confidence,
            "version": self.version,
            "usage_count": self.usage_count,
            "success_rate": self.success_rate,
            "schema": self.schema,
            "steps": self.steps,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DynamicTool":
        return cls(
            name=data["name"],
            description=data["description"],
            capabilities=data.get("capabilities", []),
            origin=data.get("origin", "user"),
            status=data.get("status", "validated"),
            confidence=data.get("confidence", 1.0),
            version=data.get("version", "1.0"),
            usage_count=data.get("usage_count", 0),
            success_rate=data.get("success_rate"),
            schema=data.get("schema", {"type": "object", "properties": {}, "required": []}),
            steps=data.get("steps", []),
        )


# ---------------------------------------------------------------------------
# DynamicToolRegistry
# ---------------------------------------------------------------------------

class DynamicToolRegistry:
    """
    Manages the full lifecycle of dynamic tools: registration, persistence,
    metrics, and promotion from candidate → production.
    """

    def __init__(self, tools_dir: str = TOOLS_DIR):
        self._tools: Dict[str, DynamicTool] = {}
        self._tools_dir = tools_dir
        os.makedirs(tools_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Disk I/O
    # ------------------------------------------------------------------

    def load_from_disk(self) -> None:
        """Load all .json files from the tools directory."""
        loaded = 0
        for fname in sorted(os.listdir(self._tools_dir)):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(self._tools_dir, fname)
            try:
                with open(path) as f:
                    data = json.load(f)
                tool = DynamicTool.from_dict(data)
                self._tools[tool.name] = tool
                loaded += 1
                logger.info(
                    f"Loaded dynamic tool: '{tool.name}' "
                    f"[{tool.status}] origin={tool.origin}"
                )
            except Exception as e:
                logger.warning(f"Failed to load tool from '{fname}': {e}")
        if loaded:
            logger.info(f"DynamicToolRegistry: loaded {loaded} tool(s) from disk.")

    def _save(self, tool: DynamicTool) -> None:
        path = os.path.join(self._tools_dir, f"{tool.name}.json")
        try:
            with open(path, "w") as f:
                json.dump(tool.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save tool '{tool.name}': {e}")

    # ------------------------------------------------------------------
    # Registry API
    # ------------------------------------------------------------------

    def register(self, tool: DynamicTool, save: bool = True) -> None:
        """Add or replace a tool in the registry and optionally persist it."""
        self._tools[tool.name] = tool
        if save:
            self._save(tool)
        logger.info(
            f"DynamicToolRegistry: registered '{tool.name}' "
            f"[{tool.status}] origin={tool.origin} confidence={tool.confidence}"
        )

    def get(self, name: str) -> Optional[DynamicTool]:
        """Return a tool by name, or None if not registered."""
        return self._tools.get(name)

    def all_tools(self) -> List[DynamicTool]:
        """Return all registered tools regardless of status."""
        return list(self._tools.values())

    def available_tools(self) -> List[DynamicTool]:
        """Return only validated + production tools (available to agents)."""
        return [t for t in self._tools.values() if t.is_available()]

    # ------------------------------------------------------------------
    # Metrics + promotion
    # ------------------------------------------------------------------

    def record_call(self, name: str, success: bool) -> bool:
        """
        Record a call outcome for a dynamic tool.
        If the tool is a candidate that now meets promotion criteria,
        promotes it to 'production' and saves.

        Returns True if the tool was promoted.
        """
        tool = self._tools.get(name)
        if tool is None:
            return False
        tool.record_call(success)
        if tool.should_promote():
            tool.status = "production"
            logger.info(
                f"DynamicTool '{name}' promoted candidate → production "
                f"(calls={tool.usage_count}, success_rate={tool.success_rate:.2f})"
            )
            self._save(tool)
            return True
        self._save(tool)
        return False
