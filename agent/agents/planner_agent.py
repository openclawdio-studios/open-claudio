"""
PlannerAgent — decomposes a user request into a DAG of sub-tasks,
each assigned to the appropriate domain agent, and executes them with
maximum parallelism while respecting declared dependencies.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Dict, List, Optional

from agents.base_agent import BaseAgent
from db import recorder

if TYPE_CHECKING:
    from context import AgentContext

logger = logging.getLogger("PlannerAgent")

_GOAL_PLANNER_PROMPT_TEMPLATE = """\
You are the Planner for Open-Claudio, an AI home automation system working toward an autonomous goal.

Your job is to decompose the goal into a list of concrete sub-tasks that will move the system
from its CURRENT STATE to the DESIRED STATE.

Available agents and their capabilities:
{agent_list}

Goal description: {description}

Current state (what we know right now):
{current_state}

Desired state (what we need to achieve):
{desired_state}

OUTPUT RULES — follow them exactly:
1. Output ONLY a valid JSON array. No markdown fences, no explanation, no preamble.
2. Each element must be an object with these keys:
   - "id"         : unique step identifier, e.g. "s0", "s1"
   - "agent"      : name of the specialist agent
   - "task"       : specific sub-task description
   - "reason"     : one-line explanation of why this step is needed
   - "priority"   : integer (1=highest)
   - "depends_on" : list of step IDs this step requires first ([] if independent)
3. Only include steps for state keys that are NOT already satisfied.
4. Steps with empty "depends_on" run IN PARALLEL — maximise parallelism.
5. If the desired state is already achieved, output an empty array: []
"""

_PLANNER_PROMPT_TEMPLATE = """\
You are the Planner for Open-Claudio, an AI home automation system.

Your job is to decompose the user's request into a list of sub-tasks,
each assigned to the most appropriate specialist agent.

Available agents and their capabilities:
{agent_list}

OUTPUT RULES — follow them exactly:
1. Output ONLY a valid JSON array. No markdown fences, no explanation, no preamble.
2. Each element must be an object with these keys:
   - "id"         : unique step identifier, e.g. "s0", "s1", "s2"
   - "agent"      : name of the specialist agent
   - "task"       : specific sub-task description
   - "reason"     : one-line explanation of why this step is needed
   - "priority"   : integer (1=highest priority, higher number=lower priority)
   - "depends_on" : list of step IDs this step requires to finish first ([] if independent)
3. Steps with empty "depends_on" run IN PARALLEL — maximise parallelism.
4. Steps that need results from prior steps MUST declare those IDs in "depends_on".
5. For a simple single-domain request produce exactly one step.
6. If in doubt, assign to "utility".

EXAMPLES:

User: "What time is it?"
Output: [{{"id":"s0","agent":"utility","task":"What is the current time?","reason":"user asked for time","priority":1,"depends_on":[]}}]

User: "Close all the blinds."
Output: [{{"id":"s0","agent":"home","task":"Close all the blinds (set_all_blinds_state to closed).","reason":"user command","priority":1,"depends_on":[]}}]

User: "What time is it and are my blinds working?"
Output: [
  {{"id":"s0","agent":"utility","task":"What is the current time?","reason":"time query","priority":1,"depends_on":[]}},
  {{"id":"s1","agent":"home","task":"Check the status of the blinds.","reason":"blinds query","priority":1,"depends_on":[]}}
]

User: "Look up the blind manual and then close the bedroom blind."
Output: [
  {{"id":"s0","agent":"knowledge","task":"Search the knowledge base for blind manual or configuration docs.","reason":"need docs before acting","priority":1,"depends_on":[]}},
  {{"id":"s1","agent":"home","task":"Close the bedroom blind (Ventana Hab. Principal).","reason":"main action, needs manual first","priority":2,"depends_on":["s0"]}}
]

User: "Open the front door and then tell me the last intercom call."
Output: [
  {{"id":"s0","agent":"home","task":"Open the front door via the intercom.","reason":"user request","priority":1,"depends_on":[]}},
  {{"id":"s1","agent":"intercom","task":"Retrieve the most recent call from the intercom history.","reason":"user request","priority":1,"depends_on":[]}}
]

User: "Read the config file at /app/config.json and fetch http://example.com/status"
Output: [
  {{"id":"s0","agent":"server","task":"Read the file at /app/config.json and return its contents.","reason":"user request","priority":1,"depends_on":[]}},
  {{"id":"s1","agent":"server","task":"Fetch http://example.com/status and return the response.","reason":"user request","priority":1,"depends_on":[]}}
]
"""


class PlannerAgent:
    """
    Orchestrator that plans and executes multi-agent workflows using a DAG.

    Steps with no declared dependencies execute in parallel via asyncio.gather.
    Steps with depends_on wait for their dependencies to complete first.

    Parameters
    ----------
    agents : dict[str, BaseAgent]
        Registry mapping agent name → BaseAgent instance.
    ctx : AgentContext
        Shared context providing llm_client, model, and services.
    """

    def __init__(
        self,
        agents: Dict[str, BaseAgent],
        ctx: AgentContext,
    ):
        self.agents = agents
        self.ctx = ctx

        # Build capability → agent_name index from registered agents
        self._capability_index: Dict[str, str] = {}
        for name, agent in agents.items():
            for cap in getattr(agent, "capabilities", []):
                self._capability_index[cap] = name

        # Build agent list string for the system prompt (dynamic, from capabilities)
        lines = []
        for name, agent in agents.items():
            caps = getattr(agent, "capabilities", [])
            caps_str = ", ".join(caps) if caps else "general"
            lines.append(f'- "{name}" [{caps_str}]')
        self._system_prompt = _PLANNER_PROMPT_TEMPLATE.format(
            agent_list="\n".join(lines)
        )

        logger.info(
            f"PlannerAgent ready. Capability index: {self._capability_index}"
        )

    # ------------------------------------------------------------------
    # Capability helpers
    # ------------------------------------------------------------------

    def _agent_for_capability(self, capability: str) -> Optional[str]:
        """Return the agent name that owns a given capability, or None."""
        return self._capability_index.get(capability)

    def _resolve_agent(self, agent_name: str) -> str:
        """
        Validate the agent name from the LLM plan.
        If the name is unknown, try to resolve it as a capability tag.
        Falls back to 'utility'.
        """
        if agent_name in self.agents:
            return agent_name
        resolved = self._agent_for_capability(agent_name)
        if resolved:
            logger.info(
                f"PlannerAgent: resolved unknown agent '{agent_name}' "
                f"to '{resolved}' via capability index"
            )
            return resolved
        logger.warning(
            f"PlannerAgent: unknown agent '{agent_name}', falling back to 'utility'"
        )
        return "utility"

    # ------------------------------------------------------------------
    # Step normalization
    # ------------------------------------------------------------------

    def _normalize_steps(self, raw_steps: list) -> List[dict]:
        """
        Ensure every step has all required DAG fields.
        The LLM might omit optional fields — this fills in safe defaults.
        Also guarantees unique IDs.
        """
        normalized = []
        ids_seen: set = set()

        for i, step in enumerate(raw_steps):
            step_id = str(step.get("id", f"s{i}"))
            # Deduplicate IDs
            if step_id in ids_seen:
                step_id = f"s{i}"
            ids_seen.add(step_id)

            normalized.append({
                "id":         step_id,
                "agent":      step.get("agent", "utility"),
                "task":       step.get("task", ""),
                "reason":     step.get("reason", ""),
                "priority":   int(step.get("priority", 1)),
                "depends_on": [str(d) for d in step.get("depends_on", [])],
            })

        return normalized

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    async def plan(self, task: str) -> List[dict]:
        """
        Ask the LLM to decompose *task* into a DAG of structured steps.
        Returns normalized steps with id, agent, task, reason, priority, depends_on.
        Falls back to a single utility step if JSON parsing fails.
        """
        span_id = await recorder.start_span("planner", "planner")
        token = recorder.set_parent_span_id(span_id)
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": task},
        ]
        t0 = time.monotonic()
        try:
            response = await self.ctx.llm_client.chat.completions.create(
                model=self.ctx.model,
                messages=messages,
                temperature=0.0,
            )
            duration_ms = int((time.monotonic() - t0) * 1000)
            usage = response.usage
            await recorder.record_llm_call(
                span_id=span_id,
                model=self.ctx.model,
                messages=messages,
                response=(response.choices[0].message.content or ""),
                tokens_prompt=usage.prompt_tokens if usage else None,
                tokens_completion=usage.completion_tokens if usage else None,
                temperature=0.0,
                stop_reason="stop",
                duration_ms=duration_ms,
            )
            raw = (response.choices[0].message.content or "").strip()

            # Strip accidental markdown fences
            if raw.startswith("```"):
                lines = raw.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                raw = "\n".join(lines).strip()

            parsed = json.loads(raw)
            if (
                isinstance(parsed, list)
                and all(isinstance(s, dict) and "agent" in s and "task" in s for s in parsed)
                and len(parsed) > 0
            ):
                steps = self._normalize_steps(parsed)
                logger.info(f"PlannerAgent produced {len(steps)} step(s): {steps}")
                await recorder.complete_span(span_id, "ok")
                return steps

            logger.warning(f"PlannerAgent returned unexpected structure: {parsed!r}")
            await recorder.complete_span(span_id, "error", "unexpected structure")
        except json.JSONDecodeError as e:
            logger.warning(f"PlannerAgent JSON parse error: {e}")
            await recorder.complete_span(span_id, "error", str(e))
        except Exception as e:
            logger.error(f"PlannerAgent plan() failed: {e}")
            await recorder.complete_span(span_id, "error", str(e))
        finally:
            recorder.reset_parent_span_id(token)

        # Safe fallback
        fallback = self._normalize_steps([{"agent": "utility", "task": task}])
        logger.info(f"PlannerAgent falling back to: {fallback}")
        return fallback

    # ------------------------------------------------------------------
    # DAG execution
    # ------------------------------------------------------------------

    async def _run_step(self, step: dict) -> str:
        """Execute a single plan step and return its result string."""
        agent_name = self._resolve_agent(step["agent"])
        sub_task = step["task"]
        reason = step.get("reason", "")

        log_msg = f"PlannerAgent → [{step['id']}] {agent_name}: '{sub_task}'"
        if reason:
            log_msg += f" (reason: {reason})"
        logger.info(log_msg)

        agent = self.agents.get(agent_name)
        if agent is None:
            msg = (
                f"[PlannerAgent] Agent '{agent_name}' not found. "
                f"Available: {list(self.agents.keys())}."
            )
            logger.error(msg)
            return msg

        try:
            return await agent.run(sub_task)
        except Exception as e:
            logger.error(f"PlannerAgent: agent '{agent_name}' raised: {e}")
            return f"[{agent_name}] Unexpected error: {e}"

    async def _execute_dag(self, steps: List[dict]) -> Dict[str, str]:
        """
        Execute steps as a DAG: steps whose dependencies are all satisfied
        are launched in parallel via asyncio.gather. Repeats until all steps
        are done or no progress can be made (cycle / missing dependency).

        Returns a dict mapping step_id → result string.
        """
        results: Dict[str, str] = {}
        pending = list(steps)

        while pending:
            # Steps whose every dependency already has a result
            ready = [
                s for s in pending
                if all(dep in results for dep in s["depends_on"])
            ]

            if not ready:
                # No progress possible — dependency cycle or bad IDs
                logger.error(
                    f"PlannerAgent DAG stalled. Pending steps: "
                    f"{[s['id'] for s in pending]}. "
                    f"Resolved so far: {list(results.keys())}"
                )
                for s in pending:
                    results[s["id"]] = (
                        f"[skipped: dependency '{s['depends_on']}' could not be resolved]"
                    )
                break

            # Sort ready batch by priority (lower number = higher priority, run first)
            ready.sort(key=lambda s: s.get("priority", 1))

            logger.info(
                f"PlannerAgent DAG batch: executing {[s['id'] for s in ready]} in parallel"
            )

            batch_results = await asyncio.gather(
                *[self._run_step(s) for s in ready],
                return_exceptions=True,
            )

            for step, result in zip(ready, batch_results):
                if isinstance(result, Exception):
                    results[step["id"]] = f"[{step['agent']}] Error: {result}"
                else:
                    results[step["id"]] = str(result)
                pending.remove(step)

        return results

    # ------------------------------------------------------------------
    # Goal-oriented planning
    # ------------------------------------------------------------------

    async def plan_from_goal(self, goal) -> List[dict]:
        """
        Decompose a Goal into a DAG of steps, using current ctx.state as
        the baseline and goal.desired_state as the target.

        Returns normalized steps (same format as plan()).
        """
        current_state = self.ctx.state or {}

        # Filter: only include desired keys not yet satisfied
        unsatisfied = {
            k: v for k, v in goal.desired_state.items()
            if current_state.get(k) != v
        }

        if not unsatisfied:
            logger.info(f"PlannerAgent.plan_from_goal: goal '{goal.id}' already satisfied.")
            return []

        current_state_str = (
            "\n".join(f"  {k}: {v}" for k, v in current_state.items())
            or "  (no state data available yet)"
        )
        desired_state_str = "\n".join(f"  {k}: {v}" for k, v in unsatisfied.items())

        prompt = _GOAL_PLANNER_PROMPT_TEMPLATE.format(
            agent_list="\n".join(
                f'- "{name}" [{", ".join(getattr(a, "capabilities", []) or ["general"])}]'
                for name, a in self.agents.items()
            ),
            description=goal.description,
            current_state=current_state_str,
            desired_state=desired_state_str,
        )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Plan steps to satisfy goal: {goal.description}"},
        ]

        span_id = await recorder.start_span("planner", f"goal:{goal.id}")
        t0 = time.monotonic()
        try:
            response = await self.ctx.llm_client.chat.completions.create(
                model=self.ctx.model,
                messages=messages,
                temperature=0.0,
            )
            duration_ms = int((time.monotonic() - t0) * 1000)
            usage = response.usage
            await recorder.record_llm_call(
                span_id=span_id,
                model=self.ctx.model,
                messages=messages,
                response=(response.choices[0].message.content or ""),
                tokens_prompt=usage.prompt_tokens if usage else None,
                tokens_completion=usage.completion_tokens if usage else None,
                temperature=0.0,
                stop_reason="stop",
                duration_ms=duration_ms,
            )
            raw = (response.choices[0].message.content or "").strip()

            if raw.startswith("```"):
                lines = raw.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                raw = "\n".join(lines).strip()

            parsed = json.loads(raw)
            if isinstance(parsed, list):
                steps = self._normalize_steps(parsed)
                logger.info(
                    f"PlannerAgent.plan_from_goal '{goal.id}': {len(steps)} step(s)"
                )
                await recorder.complete_span(span_id, "ok")
                return steps

            await recorder.complete_span(span_id, "error", "unexpected structure")
        except json.JSONDecodeError as e:
            logger.warning(f"PlannerAgent.plan_from_goal JSON parse error: {e}")
            await recorder.complete_span(span_id, "error", str(e))
        except Exception as e:
            logger.error(f"PlannerAgent.plan_from_goal failed: {e}")
            await recorder.complete_span(span_id, "error", str(e))

        # Fallback: treat goal description as a plain task
        fallback = self._normalize_steps([{"agent": "utility", "task": goal.description}])
        logger.info(f"PlannerAgent.plan_from_goal falling back to: {fallback}")
        return fallback

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def run(self, task: str) -> str:
        """
        Plan the task and execute it as a DAG.
        Returns a combined result string in original step order.
        """
        steps = await self.plan(task)

        # Persist the plan on the active trace
        trace_id = recorder.get_trace_id()
        if trace_id:
            try:
                from db.connection import AsyncSessionFactory
                from db.models import Trace
                async with AsyncSessionFactory() as session:
                    async with session.begin():
                        row = await session.get(Trace, trace_id)
                        if row:
                            row.agent_plan = steps
            except Exception:
                pass

        results_by_id = await self._execute_dag(steps)

        # Return results in original step order
        ordered = [
            results_by_id.get(step["id"], "[no result]")
            for step in steps
        ]
        return "\n\n".join(ordered) if ordered else "No steps were executed."
