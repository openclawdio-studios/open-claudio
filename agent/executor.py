"""
Executor — responsible for all tool execution, self-healing, and metrics.

BaseAgent delegates every tool call here. This layer owns:
  - raw dispatch (local tools vs MCP vs generated tools vs create_tool meta)
  - self-healing: retry, LLM parameter correction, fix memory
  - tool metrics recording
  - DB observability for tool calls
  - auto-detection of repetitive patterns → candidate tool creation
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Dict, List, Optional

from tools import LOCAL_TOOLS, TOOL_CAPABILITIES
from db import recorder
from tool_healing import (
    parse_tool_result,
    get_strategy,
    build_repair_prompt,
    parse_llm_fix,
    lookup_known_fix,
    record_fix,
    record_metric,
    should_avoid_tool,
    MAX_HEAL_RETRIES,
)

if TYPE_CHECKING:
    from context import AgentContext

logger = logging.getLogger("Executor")

# ---------------------------------------------------------------------------
# create_tool meta-tool schema (always injected into every agent's tool list)
# ---------------------------------------------------------------------------

_CREATE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_tool",
        "description": (
            "Create and persist a new reusable tool (routine). "
            "Use ONLY when the user explicitly asks to create a reusable command, "
            "routine, or shortcut. Define steps as a sequence of existing tool calls."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Tool name in snake_case (no spaces, lowercase)",
                },
                "description": {
                    "type": "string",
                    "description": "What this tool does in plain language",
                },
                "steps": {
                    "type": "array",
                    "description": "Ordered list of tool calls that implement this routine",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {
                                "type": "string",
                                "description": "Name of an existing tool to call",
                            },
                            "args": {
                                "type": "object",
                                "description": "Arguments for the tool call",
                            },
                        },
                        "required": ["tool", "args"],
                    },
                },
            },
            "required": ["name", "description", "steps"],
        },
    },
}

# How many consecutive calls to the same tool trigger auto-candidate creation
_AUTO_DETECT_THRESHOLD = 3


class Executor:
    """
    Executes tool calls on behalf of any agent, with self-healing, dynamic
    tool support, and session-level pattern detection.

    Parameters
    ----------
    ctx : AgentContext
        Shared context providing services and scratchpad.
    """

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
        # Per-session, per-agent call log for auto-detection
        # agent_name → [{tool, args}]
        self._session_calls: Dict[str, List[dict]] = {}

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def mcp_client(self):
        return self.ctx.mcp_client

    @property
    def llm_client(self):
        return self.ctx.llm_client

    @property
    def model(self):
        return self.ctx.model

    @property
    def memory(self):
        return self.ctx.memory

    # ------------------------------------------------------------------
    # Memory namespace
    # ------------------------------------------------------------------

    def _mem(self, agent_name: str) -> dict:
        """Return (and lazily create) the per-agent healing memory sub-dict."""
        return self.memory.setdefault(agent_name, {})

    # ------------------------------------------------------------------
    # Tool building (called by BaseAgent to populate LLM tool list)
    # ------------------------------------------------------------------

    def build_tools(self, tool_names: set) -> list:
        """
        Build the OpenAI function-calling tool list.
        Includes: whitelisted local tools + whitelisted MCP tools
                + all available generated tools (not subject to whitelist)
                + create_tool meta-tool (always present).
        """
        tools = []

        for name, tool_info in LOCAL_TOOLS.items():
            if name not in tool_names:
                continue
            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool_info["description"],
                    "parameters": tool_info.get("schema", {"type": "object", "properties": {}}),
                },
            })

        for t in self.mcp_client.get_available_tools():
            if t.name not in tool_names:
                continue
            tools.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or f"MCP tool {t.name}",
                    "parameters": t.inputSchema,
                },
            })

        # Generated tools — available regardless of whitelist
        if self.ctx.registry:
            for dyn in self.ctx.registry.available_tools():
                tools.append({
                    "type": "function",
                    "function": {
                        "name": dyn.name,
                        "description": dyn.description,
                        "parameters": dyn.schema,
                    },
                })

        # create_tool meta-tool — always last, always present
        tools.append(_CREATE_TOOL_SCHEMA)

        return tools

    # ------------------------------------------------------------------
    # Capability metadata
    # ------------------------------------------------------------------

    def get_tool_capabilities(self, tool_name: str) -> list:
        """Return capability tags for a tool, or empty list if unknown."""
        return TOOL_CAPABILITIES.get(tool_name, [])

    # ------------------------------------------------------------------
    # Tool metadata (version + runtime reliability)
    # ------------------------------------------------------------------

    def get_tool_metadata(self, tool_name: str, agent_name: Optional[str] = None) -> dict:
        """
        Return enriched metadata for a tool:
          - version     : from MCP server if provided, else "1.0"
          - server      : which MCP server owns the tool (or "local" / "generated")
          - calls       : total recorded calls (from memory metrics)
          - success_rate: computed from memory metrics (None if no data)

        Parameters
        ----------
        tool_name  : tool to query
        agent_name : if provided, reads per-agent metrics from memory
        """
        source = self._tool_source(tool_name)
        version = self.mcp_client.get_tool_version(tool_name)

        calls = 0
        success_rate = None
        if agent_name:
            mem_ns = self._mem(agent_name)
            stats = mem_ns.get("tool_metrics", {}).get(tool_name, {})
            calls = stats.get("calls", 0)
            errors = stats.get("errors", 0)
            if calls > 0:
                success_rate = round((calls - errors) / calls, 4)

        return {
            "name": tool_name,
            "version": version,
            "source": source,
            "calls": calls,
            "success_rate": success_rate,
        }

    # ------------------------------------------------------------------
    # Memory helper for BaseAgent (LLM-visible memory, no healing internals)
    # ------------------------------------------------------------------

    def get_agent_memory_for_llm(self, agent_name: str) -> dict:
        """Return per-agent memory excluding healing internals (not shown to LLM)."""
        mem_ns = self._mem(agent_name)
        return {k: v for k, v in mem_ns.items() if k not in ("tool_fixes", "tool_metrics")}

    # ------------------------------------------------------------------
    # Tool source detection (for observability)
    # ------------------------------------------------------------------

    def _tool_source(self, name: str) -> str:
        """Return which server/layer owns the tool (for DB recording)."""
        if name == "create_tool":
            return "meta"
        if self.ctx.registry and self.ctx.registry.get(name):
            return "generated"
        if name in LOCAL_TOOLS:
            return "local"
        for url, conn in self.mcp_client.connections.items():
            if any(t.name == name for t in conn.get("tools", [])):
                try:
                    return url.split("//")[1].split(":")[0]
                except Exception:
                    return "mcp_unknown"
        return "unknown"

    # ------------------------------------------------------------------
    # create_tool handler
    # ------------------------------------------------------------------

    async def _handle_create_tool(self, arguments: dict) -> str:
        """Create, register, and persist a new user-defined tool."""
        from tools_registry import DynamicTool

        name = arguments.get("name", "").strip().replace(" ", "_")
        description = arguments.get("description", "")
        steps = arguments.get("steps", [])

        if not name:
            return "Error: tool name is required."
        if not steps:
            return "Error: steps list is required and cannot be empty."

        if self.ctx.registry is None:
            return "Error: tool registry is not available."

        # Infer capabilities from the tools used in steps
        caps: list = []
        for step in steps:
            tool_name = step.get("tool", "")
            for cap in self.get_tool_capabilities(tool_name):
                if cap not in caps:
                    caps.append(cap)

        tool = DynamicTool(
            name=name,
            description=description,
            capabilities=caps,
            origin="user",
            status="validated",
            confidence=1.0,
            version="1.0",
            usage_count=0,
            success_rate=None,
            schema={"type": "object", "properties": {}, "required": []},
            steps=steps,
        )
        self.ctx.registry.register(tool)
        return (
            f"Tool '{name}' created successfully with {len(steps)} step(s). "
            f"It is now available for immediate use."
        )

    # ------------------------------------------------------------------
    # Generated tool execution
    # ------------------------------------------------------------------

    async def _execute_generated_steps(self, tool_name: str, steps: List[dict]) -> str:
        """Execute a generated tool by running its steps sequentially."""
        results = []
        for i, step in enumerate(steps):
            sub_tool = step.get("tool", "")
            sub_args = step.get("args", {})
            if not sub_tool:
                results.append(f"[step {i}] Error: missing tool name")
                continue
            logger.info(f"[generated:{tool_name}] step {i}: {sub_tool}({sub_args})")
            result = await self._raw_execute(sub_tool, sub_args)
            results.append(f"[{sub_tool}]: {result}")
        return "\n".join(results)

    # ------------------------------------------------------------------
    # Auto-detection of repetitive patterns
    # ------------------------------------------------------------------

    def _track_and_detect(self, agent_name: str, tool_name: str, args: dict) -> None:
        """
        Track tool calls in the session log. When the same tool is called
        _AUTO_DETECT_THRESHOLD times in a row, create an auto-candidate tool
        that encapsulates those calls.
        """
        if self.ctx.registry is None:
            return
        # Skip meta-tools and already-generated tools
        if tool_name in ("create_tool",) or self.ctx.registry.get(tool_name):
            return

        log = self._session_calls.setdefault(agent_name, [])
        log.append({"tool": tool_name, "args": dict(args)})

        # Keep only last 10 entries
        if len(log) > 10:
            log.pop(0)

        if len(log) < _AUTO_DETECT_THRESHOLD:
            return

        last_n = log[-_AUTO_DETECT_THRESHOLD:]
        if len(set(c["tool"] for c in last_n)) != 1:
            return  # Not all the same tool

        candidate_name = f"auto_{tool_name}_batch"
        if self.ctx.registry.get(candidate_name):
            return  # Already exists

        from tools_registry import DynamicTool
        candidate = DynamicTool(
            name=candidate_name,
            description=(
                f"Auto-detected routine: repeats '{tool_name}' "
                f"with the last {_AUTO_DETECT_THRESHOLD} argument sets."
            ),
            capabilities=self.get_tool_capabilities(tool_name),
            origin="auto",
            status="candidate",
            confidence=0.65,
            version="1.0",
            usage_count=0,
            success_rate=None,
            schema={"type": "object", "properties": {}, "required": []},
            steps=[{"tool": c["tool"], "args": c["args"]} for c in last_n],
        )
        self.ctx.registry.register(candidate)
        logger.info(
            f"[auto-detect] Created candidate tool '{candidate_name}' "
            f"from {_AUTO_DETECT_THRESHOLD} repeated calls to '{tool_name}'"
        )

    # ------------------------------------------------------------------
    # Raw execution (no healing)
    # ------------------------------------------------------------------

    async def _raw_execute(self, name: str, arguments: dict) -> str:
        """Dispatch a tool call without any healing logic."""
        # Meta-tool: create_tool
        if name == "create_tool":
            return await self._handle_create_tool(arguments)

        # Generated tools registry
        if self.ctx.registry:
            dyn = self.ctx.registry.get(name)
            if dyn and dyn.is_available():
                logger.info(f"Executing generated tool: {name} [{dyn.status}]")
                result = await self._execute_generated_steps(name, dyn.steps)
                return result

        # Local tools
        if name in LOCAL_TOOLS:
            logger.info(f"Executing local tool: {name}")
            try:
                fn = LOCAL_TOOLS[name]["function"]
                result = fn(**arguments)
                return str(result)
            except Exception as e:
                return f"Error executing local tool {name}: {str(e)}"

        # MCP remote tools
        mcp_tools = self.mcp_client.get_available_tools()
        if any(t.name == name for t in mcp_tools):
            return await self.mcp_client.call_tool(name, arguments)

        all_tool_names = (
            list(LOCAL_TOOLS.keys())
            + [t.name for t in mcp_tools]
            + ([t.name for t in self.ctx.registry.available_tools()] if self.ctx.registry else [])
        )
        return json.dumps({
            "status": "error",
            "error_type": "tool_not_found",
            "message": f"Tool '{name}' is not available right now.",
            "available_tools": all_tool_names,
        })

    # ------------------------------------------------------------------
    # Healing execution (public interface for BaseAgent)
    # ------------------------------------------------------------------

    async def execute(self, agent_name: str, name: str, arguments: dict) -> str:
        """
        Execute a tool with full self-healing: known-fix lookup, retry,
        LLM parameter correction. Records metrics and DB observability.
        Also updates dynamic tool metrics and runs auto-detection.
        """
        _known_fix_applied = False
        _retries = 0
        _healing_strategy: Optional[str] = None
        _success = False
        _error_type: Optional[str] = None
        _output = ""
        original_arguments = dict(arguments)
        tool_span_id = await recorder.start_span("tool_call", name)
        t0 = time.monotonic()

        try:
            # create_tool and generated tools skip healing entirely
            if name == "create_tool" or (
                self.ctx.registry and (dyn := self.ctx.registry.get(name)) and dyn.is_available()
            ):
                _output = await self._raw_execute(name, arguments)
                _success = not _output.startswith("Error")
                if self.ctx.registry and name != "create_tool":
                    self.ctx.registry.record_call(name, _success)
                return _output

            mem_ns = self._mem(agent_name)

            # Avoidance check: skip tools with persistently poor reliability
            avoid, avoid_reason = should_avoid_tool(mem_ns, name)
            if avoid:
                _error_type = "tool_degraded"
                _output = (
                    f"Tool '{name}' is currently unreliable and has been skipped. "
                    f"Reason: {avoid_reason}. "
                    f"Please inform the user this action cannot be completed reliably."
                )
                logger.warning(f"[{agent_name}] Avoiding degraded tool '{name}': {avoid_reason}")
                return _output

            # Step 1: Apply known fix from memory if available
            fixed_args = lookup_known_fix(mem_ns, name, arguments)
            if fixed_args is not None:
                logger.info(f"[{agent_name}] Applying known fix for '{name}': {arguments} → {fixed_args}")
                arguments = fixed_args
                _known_fix_applied = True

            # Step 2: Execute and parse
            raw = await self._raw_execute(name, arguments)
            result = parse_tool_result(raw)
            record_metric(mem_ns, name, result.success, result.error_type)

            if result.success:
                _success, _output = True, result.content
                # Auto-detection: track successful calls
                self._track_and_detect(agent_name, name, arguments)
                return result.content

            # Step 3: Determine healing strategy
            strategy = get_strategy(result.error_type)
            _error_type = result.error_type
            logger.warning(
                f"[{agent_name}] Tool '{name}' failed "
                f"(type={result.error_type}, strategy={strategy}): {result.content}"
            )

            # --- Strategy: retry ---
            if strategy in ("retry", "retry_then_report"):
                _healing_strategy = "retry"
                for attempt in range(1, MAX_HEAL_RETRIES + 1):
                    _retries += 1
                    logger.info(f"[{agent_name}] Retry {attempt}/{MAX_HEAL_RETRIES} for '{name}'")
                    await asyncio.sleep(1.5 * attempt)
                    raw = await self._raw_execute(name, arguments)
                    result = parse_tool_result(raw)
                    record_metric(mem_ns, name, result.success, result.error_type)
                    if result.success:
                        _success, _output = True, result.content
                        self._track_and_detect(agent_name, name, arguments)
                        return result.content
                _output = f"Tool '{name}' failed after {MAX_HEAL_RETRIES} retries: {result.content}"
                return _output

            # --- Strategy: llm_fix ---
            if strategy == "llm_fix":
                _healing_strategy = "llm_fix"
                repair_prompt = build_repair_prompt(name, arguments, result)
                logger.info(f"[{agent_name}] Requesting LLM to fix params for '{name}'")
                try:
                    fix_response = await self.llm_client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": repair_prompt}],
                        temperature=0.0,
                    )
                    fix_text = fix_response.choices[0].message.content or ""
                    new_args = parse_llm_fix(fix_text)

                    if new_args and new_args != arguments:
                        logger.info(f"[{agent_name}] LLM suggested fix: {arguments} → {new_args}")
                        raw = await self._raw_execute(name, new_args)
                        result = parse_tool_result(raw)
                        record_metric(mem_ns, name, result.success, result.error_type)
                        if result.success:
                            record_fix(mem_ns, name, original_arguments, new_args)
                            await recorder.upsert_tool_fix(
                                agent_name, name, original_arguments, new_args
                            )
                            _success, _output = True, result.content
                            self._track_and_detect(agent_name, name, new_args)
                            return result.content
                        else:
                            _output = f"Tool '{name}' still failed after LLM correction: {result.content}"
                            return _output
                    else:
                        logger.warning(f"[{agent_name}] LLM could not suggest a valid fix.")
                except Exception as e:
                    logger.error(f"[{agent_name}] LLM fix call failed: {e}")

            # --- Strategy: report ---
            if result.error_type == "tool_not_found" and result.raw and isinstance(result.raw, dict):
                avail = result.raw.get("available_tools", [])
                if avail:
                    _output = (
                        f"Tool '{name}' does not exist. "
                        f"Available tools: {', '.join(avail)}. "
                        f"Please use one of the available tools instead."
                    )
                    return _output

            _output = f"Tool '{name}' error ({result.error_type}): {result.content}"
            return _output

        finally:
            duration_ms = int((time.monotonic() - t0) * 1000)
            await recorder.record_tool_call(
                span_id=tool_span_id,
                tool_name=name,
                tool_source=self._tool_source(name),
                input_args=original_arguments,
                output=_output,
                success=_success,
                error_type=_error_type,
                healing_strategy=_healing_strategy,
                retries=_retries,
                known_fix_applied=_known_fix_applied,
                duration_ms=duration_ms,
            )
            await recorder.complete_span(
                tool_span_id,
                "ok" if _success else "error",
                duration_ms=duration_ms,
            )
            if _success:
                self.ctx.last_tool_call = {
                    "tool": name,
                    "args": original_arguments,
                    "agent": agent_name,
                }
