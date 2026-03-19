"""
BaseAgent — the reusable ReAct loop used by every domain agent.

Each agent is constructed with a whitelist of tool names and an AgentContext.
The agent is responsible only for reasoning: building prompts, calling the LLM,
and interpreting responses. All tool execution, healing, and metrics are
delegated to ctx.executor.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import TYPE_CHECKING, Optional

from db import recorder

if TYPE_CHECKING:
    from context import AgentContext

# ---------------------------------------------------------------------------
# Correction detection
# ---------------------------------------------------------------------------

# Each entry: (compiled_pattern, wrong_group_index_or_None, correct_group_index)
_CORRECTION_PATTERNS = [
    # "no era el salon, era el dormitorio" → wrong=salon, correct=dormitorio
    (re.compile(r"no era (?:el |la )?(.+?),?\s+era (?:el |la )?(.+)", re.I), 1, 2),
    # "me refería a X" → correct=X
    (re.compile(r"me refer[íi]a a (.+)", re.I), None, 1),
    # "quería decir X" → correct=X
    (re.compile(r"quer[íi]a decir (.+)", re.I), None, 1),
    # "no X, Y" (generic fallback) → wrong=X, correct=Y
    (re.compile(r"\bno\s+(.+?),\s+(.+)", re.I), 1, 2),
]


def _detect_correction(message: str) -> Optional[dict]:
    """
    Return {wrong_value, correct_value} if the message looks like a user
    correction, or None if no pattern matches.
    """
    for pattern, wrong_grp, correct_grp in _CORRECTION_PATTERNS:
        m = pattern.search(message)
        if m:
            wrong = m.group(wrong_grp).strip() if wrong_grp else None
            correct = m.group(correct_grp).strip()
            return {"wrong_value": wrong, "correct_value": correct}
    return None

MAX_STEPS = int(os.getenv("MAX_STEPS", "8"))

logger = logging.getLogger("BaseAgent")


class BaseAgent:
    """
    A single-domain ReAct agent. Owns only reasoning logic.

    Parameters
    ----------
    name : str
        Unique identifier for this agent (used for logging and memory namespacing).
    tool_names : list[str]
        Whitelist of tool names this agent is allowed to use.
    ctx : AgentContext
        Shared context providing executor, llm_client, model, and memory.
    system_prompt_extra : str
        Additional instructions appended to the base system prompt.
    """

    def __init__(
        self,
        name: str,
        tool_names: list,
        ctx: AgentContext,
        system_prompt_extra: str = "",
        capabilities: list = None,
    ):
        self.name = name
        self.tool_names = set(tool_names)
        self.ctx = ctx
        self.system_prompt_extra = system_prompt_extra
        self.capabilities: list = capabilities or []

    # ------------------------------------------------------------------
    # Tool building
    # ------------------------------------------------------------------

    def _build_tools(self) -> list:
        """Build the OpenAI function-calling tool list via the executor."""
        return self.ctx.executor.build_tools(self.tool_names)

    # ------------------------------------------------------------------
    # ReAct loop
    # ------------------------------------------------------------------

    async def run(self, task: str) -> str:
        """Run the ReAct loop for a given task and return the final answer."""
        # Detect and persist user corrections before entering the ReAct loop
        correction = _detect_correction(task)
        if correction and self.ctx.last_tool_call:
            ltc = self.ctx.last_tool_call
            await recorder.record_correction(
                raw_message=task,
                agent_name=ltc.get("agent"),
                tool_name=ltc.get("tool"),
                wrong_value=correction["wrong_value"],
                correct_value=correction["correct_value"],
            )
            logger.info(
                f"[{self.name}] Correction detected — "
                f"wrong={correction['wrong_value']!r}, "
                f"correct={correction['correct_value']!r} "
                f"(last tool: {ltc.get('tool')})"
            )

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

        llm_memory = self.ctx.executor.get_agent_memory_for_llm(self.name)

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
                    "model": self.ctx.model,
                    "messages": messages,
                    "temperature": 0.2,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"

                response = await self.ctx.llm_client.chat.completions.create(**kwargs)
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
                model=self.ctx.model,
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
                    observation = await self.ctx.executor.execute(self.name, fn_name, args)
                    logger.info(f"[{self.name}] Tool result: {observation[:200]}...")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(observation),
                    })
            else:
                return message.content or ""

        return "Max reasoning steps reached without final answer."
