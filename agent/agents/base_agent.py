"""
BaseAgent — the reusable ReAct loop used by every domain agent.

Each agent is constructed with a whitelist of tool names; only those tools
are exposed to the LLM, and only those tools can be executed.  Self-healing
(retry, LLM parameter correction, fix memory) is built in, with per-agent
memory namespacing so fix data stays isolated.
"""

import asyncio
import json
import logging
import os
import time
from typing import List, Optional

from openai import AsyncOpenAI

from tools import LOCAL_TOOLS
from mcp_client import MultiMCPClient
from db import recorder
from tool_healing import (
    parse_tool_result,
    get_strategy,
    build_repair_prompt,
    parse_llm_fix,
    lookup_known_fix,
    record_fix,
    record_metric,
    MAX_HEAL_RETRIES,
)

MAX_STEPS = int(os.getenv("MAX_STEPS", "8"))

logger = logging.getLogger("BaseAgent")


class BaseAgent:
    """
    A single-domain ReAct agent.

    Parameters
    ----------
    name : str
        Unique identifier for this agent (used for logging and memory namespacing).
    tool_names : list[str]
        Whitelist of tool names this agent is allowed to use.
    mcp_client : MultiMCPClient
        Shared MCP client for remote tool calls.
    memory : dict
        Shared top-level memory dict.  The agent reads/writes only to the
        sub-dict ``memory[name]``.
    llm_client : AsyncOpenAI
        Pre-constructed async OpenAI-compatible client.
    model : str
        Model identifier string sent to the LLM API.
    system_prompt_extra : str
        Additional instructions appended to the base system prompt.
    """

    def __init__(
        self,
        name: str,
        tool_names: List[str],
        mcp_client: MultiMCPClient,
        memory: dict,
        llm_client: AsyncOpenAI,
        model: str,
        system_prompt_extra: str = "",
    ):
        self.name = name
        self.tool_names = set(tool_names)
        self.mcp_client = mcp_client
        self.memory = memory
        self.llm_client = llm_client
        self.model = model
        self.system_prompt_extra = system_prompt_extra

    # ------------------------------------------------------------------
    # Memory namespace helper
    # ------------------------------------------------------------------

    def _mem(self) -> dict:
        """Return (and lazily create) the per-agent memory sub-dict."""
        return self.memory.setdefault(self.name, {})

    # ------------------------------------------------------------------
    # Tool source detection (for observability)
    # ------------------------------------------------------------------

    def _tool_source(self, name: str) -> str:
        """Return which server/layer owns the tool (for DB recording)."""
        if name in LOCAL_TOOLS:
            return "local"
        for url, conn in self.mcp_client.connections.items():
            if any(t.name == name for t in conn.get("tools", [])):
                try:
                    return url.split("//")[1].split(":")[0]  # e.g. "mcp_domotics"
                except Exception:
                    return "mcp_unknown"
        return "unknown"

    # ------------------------------------------------------------------
    # Tool building
    # ------------------------------------------------------------------

    def _build_tools(self) -> list:
        """
        Build the OpenAI function-calling tool list, filtered to only the
        tools in ``self.tool_names``.
        """
        tools = []

        # Local tools — include only those in the whitelist
        for name, tool_info in LOCAL_TOOLS.items():
            if name not in self.tool_names:
                continue
            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool_info["description"],
                    "parameters": tool_info.get("schema", {"type": "object", "properties": {}}),
                },
            })

        # MCP remote tools — include only those in the whitelist
        mcp_tools = self.mcp_client.get_available_tools()
        for t in mcp_tools:
            if t.name not in self.tool_names:
                continue
            tools.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or f"MCP tool {t.name}",
                    "parameters": t.inputSchema,
                },
            })

        return tools

    # ------------------------------------------------------------------
    # Raw execution (no healing)
    # ------------------------------------------------------------------

    async def _raw_execute_tool(self, name: str, arguments: dict) -> str:
        """Execute a whitelisted tool without any healing logic."""
        if name not in self.tool_names:
            return json.dumps({
                "status": "error",
                "error_type": "tool_not_found",
                "message": (
                    f"Tool '{name}' is not in the allowed tool list for agent '{self.name}'. "
                    f"Allowed tools: {sorted(self.tool_names)}"
                ),
            })

        # Local tools have priority
        if name in LOCAL_TOOLS:
            logger.info(f"[{self.name}] Executing local tool: {name}")
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

        # Tool in whitelist but not currently available
        all_tool_names = list(LOCAL_TOOLS.keys()) + [t.name for t in mcp_tools]
        return json.dumps({
            "status": "error",
            "error_type": "tool_not_found",
            "message": f"Tool '{name}' is not available right now.",
            "available_tools": all_tool_names,
        })

    # ------------------------------------------------------------------
    # Healing execution
    # ------------------------------------------------------------------

    async def _execute_tool(self, name: str, arguments: dict) -> str:
        """Execute a tool with self-healing: retry, LLM param correction, fix memory."""
        # --- Observability tracking ---
        _known_fix_applied = False
        _retries = 0
        _healing_strategy: Optional[str] = None
        _success = False
        _error_type: Optional[str] = None
        _output = ""
        tool_span_id = await recorder.start_span("tool_call", name)
        t0 = time.monotonic()

        try:
            mem_ns = self._mem()
            original_arguments = dict(arguments)

            # Step 1: Apply known fix from memory if available
            fixed_args = lookup_known_fix(mem_ns, name, arguments)
            if fixed_args is not None:
                logger.info(f"[{self.name}] Applying known fix for '{name}': {arguments} → {fixed_args}")
                arguments = fixed_args
                _known_fix_applied = True

            # Step 2: Execute and parse
            raw = await self._raw_execute_tool(name, arguments)
            result = parse_tool_result(raw)
            record_metric(mem_ns, name, result.success, result.error_type)

            if result.success:
                _success, _output = True, result.content
                return result.content

            # Step 3: Determine healing strategy
            strategy = get_strategy(result.error_type)
            _error_type = result.error_type
            logger.warning(
                f"[{self.name}] Tool '{name}' failed "
                f"(type={result.error_type}, strategy={strategy}): {result.content}"
            )

            # --- Strategy: retry (connection / timeout errors) ---
            if strategy in ("retry", "retry_then_report"):
                _healing_strategy = "retry"
                for attempt in range(1, MAX_HEAL_RETRIES + 1):
                    _retries += 1
                    logger.info(f"[{self.name}] Retry {attempt}/{MAX_HEAL_RETRIES} for '{name}'")
                    await asyncio.sleep(1.5 * attempt)
                    raw = await self._raw_execute_tool(name, arguments)
                    result = parse_tool_result(raw)
                    record_metric(mem_ns, name, result.success, result.error_type)
                    if result.success:
                        _success, _output = True, result.content
                        return result.content
                _output = f"Tool '{name}' failed after {MAX_HEAL_RETRIES} retries: {result.content}"
                return _output

            # --- Strategy: llm_fix (validation errors) ---
            if strategy == "llm_fix":
                _healing_strategy = "llm_fix"
                repair_prompt = build_repair_prompt(name, arguments, result)
                logger.info(f"[{self.name}] Requesting LLM to fix params for '{name}'")
                try:
                    fix_response = await self.llm_client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": repair_prompt}],
                        temperature=0.0,
                    )
                    fix_text = fix_response.choices[0].message.content or ""
                    new_args = parse_llm_fix(fix_text)

                    if new_args and new_args != arguments:
                        logger.info(f"[{self.name}] LLM suggested fix: {arguments} → {new_args}")
                        raw = await self._raw_execute_tool(name, new_args)
                        result = parse_tool_result(raw)
                        record_metric(mem_ns, name, result.success, result.error_type)
                        if result.success:
                            record_fix(mem_ns, name, original_arguments, new_args)
                            await recorder.upsert_tool_fix(
                                self.name, name, original_arguments, new_args
                            )
                            _success, _output = True, result.content
                            return result.content
                        else:
                            _output = f"Tool '{name}' still failed after LLM correction: {result.content}"
                            return _output
                    else:
                        logger.warning(f"[{self.name}] LLM could not suggest a valid fix.")
                except Exception as e:
                    logger.error(f"[{self.name}] LLM fix call failed: {e}")

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
                input_args=original_arguments if "original_arguments" in dir() else arguments,
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

    # ------------------------------------------------------------------
    # ReAct loop
    # ------------------------------------------------------------------

    async def run(self, task: str) -> str:
        """Run the ReAct loop for a given task and return the final answer."""
        # --- Observability: agent_run span ---
        agent_span_id = await recorder.start_span("agent_run", self.name)
        parent_token = recorder.set_parent_span_id(agent_span_id)
        t_agent = time.monotonic()

        try:
            result = await self._react_loop(task, agent_span_id)
            await recorder.complete_span(
                agent_span_id, "ok",
                duration_ms=int((time.monotonic() - t_agent) * 1000),
            )
            return result
        except Exception as exc:
            await recorder.complete_span(
                agent_span_id, "error",
                error_message=str(exc),
                duration_ms=int((time.monotonic() - t_agent) * 1000),
            )
            raise
        finally:
            recorder.reset_parent_span_id(parent_token)

    async def _react_loop(self, task: str, agent_span_id: Optional[str]) -> str:
        """Inner ReAct loop — separated so run() can cleanly manage the span."""
        tools = self._build_tools()
        tool_names = [t["function"]["name"] for t in tools]
        tool_list_str = ", ".join(f"`{n}`" for n in tool_names)

        # Expose only user-facing memory to the LLM (exclude healing internals)
        mem_ns = self._mem()
        llm_memory = {k: v for k, v in mem_ns.items()
                      if k not in ("tool_fixes", "tool_metrics")}

        base_prompt = (
            f"You are '{self.name}', a specialised sub-agent of Open-Claudio.\n"
            f"You have access to a curated set of tools via function calling.\n"
            f"CRITICAL INSTRUCTIONS:\n"
            f"1. You MUST use the provided tools to fulfil the task.\n"
            f"2. DO NOT make up or hallucinate tool names. "
            f"ONLY use tools from the available list.\n"
            f"3. Available tools: {tool_list_str}\n"
            f"4. Only reply directly without tool calls for pure conversation.\n"
            f"\nMemory Context: {json.dumps(llm_memory)}\n"
        )

        if self.system_prompt_extra:
            base_prompt += f"\n{self.system_prompt_extra}\n"

        messages = [
            {"role": "system", "content": base_prompt},
            {"role": "user", "content": task},
        ]

        logger.info(f"[{self.name}] Starting task with {len(tools)} tools: {tool_names}")

        for step in range(MAX_STEPS):
            logger.info(f"[{self.name}] --- Step {step + 1}/{MAX_STEPS} ---")

            llm_span_id = await recorder.start_span("llm_call", f"{self.name}:step{step + 1}")
            t_llm = time.monotonic()
            try:
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.2,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"

                response = await self.llm_client.chat.completions.create(**kwargs)
                llm_duration = int((time.monotonic() - t_llm) * 1000)
            except Exception as e:
                llm_duration = int((time.monotonic() - t_llm) * 1000)
                await recorder.complete_span(llm_span_id, "error", str(e), llm_duration)
                logger.error(f"[{self.name}] LLM call failed: {e}")
                return f"Error communicating with LLM: {str(e)}"

            message = response.choices[0].message
            usage = response.usage
            stop_reason = "tool_calls" if message.tool_calls else "stop"

            await recorder.record_llm_call(
                span_id=llm_span_id,
                model=self.model,
                messages=messages,
                response=message.content or "",
                tokens_prompt=usage.prompt_tokens if usage else None,
                tokens_completion=usage.completion_tokens if usage else None,
                temperature=0.2,
                stop_reason=stop_reason,
                duration_ms=llm_duration,
            )
            await recorder.complete_span(llm_span_id, "ok", duration_ms=llm_duration)

            messages.append(message)

            if message.tool_calls:
                for tool_call in message.tool_calls:
                    fn_name = tool_call.function.name
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except Exception:
                        args = {}

                    logger.info(f"[{self.name}] Tool call requested: {fn_name}({args})")
                    observation = await self._execute_tool(fn_name, args)
                    logger.info(f"[{self.name}] Tool result: {observation[:200]}...")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(observation),
                    })
            else:
                # No tool calls — LLM has produced a final answer
                return message.content or ""

        return "Max reasoning steps reached without final answer."
