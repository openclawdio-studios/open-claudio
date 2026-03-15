"""
PlannerAgent — decomposes a user request into an ordered list of sub-tasks,
each assigned to the appropriate domain agent, then executes them in sequence
and returns a combined result.
"""

import json
import logging
from typing import Dict, List

from openai import AsyncOpenAI

from agents.base_agent import BaseAgent

logger = logging.getLogger("PlannerAgent")

PLANNER_SYSTEM_PROMPT = """You are the Planner for Open-Claudio, an AI home automation system.

Your job is to decompose the user's request into an ordered list of sub-tasks,
each assigned to the most appropriate specialist agent.

Available agents and their domains:
- "home"     : blinds, shutters (persianas), opening the front door via intercom
- "server"   : reading files, listing directories, making HTTP requests, server diagnostics
- "intercom" : Fermax intercom account info, device status, call history
- "utility"  : current time, generic HTTP lookups, anything that doesn't fit elsewhere

OUTPUT RULES — follow them exactly:
1. Output ONLY a valid JSON array. No markdown fences, no explanation, no preamble.
2. Each element must be an object with exactly two keys: "agent" and "task".
3. For a simple single-domain request produce exactly one step.
4. For multi-domain requests produce multiple ordered steps.
5. If in doubt, assign to "utility".

EXAMPLES:

User: "What time is it?"
Output: [{"agent": "utility", "task": "What is the current time?"}]

User: "Close all the blinds."
Output: [{"agent": "home", "task": "Close all the blinds (set_all_blinds_state to closed)."}]

User: "Open the front door and then tell me the last intercom call."
Output: [
  {"agent": "home", "task": "Open the front door via the intercom."},
  {"agent": "intercom", "task": "Retrieve the most recent call from the intercom history."}
]

User: "Read the config file at /app/config.json and fetch http://example.com/status"
Output: [
  {"agent": "server", "task": "Read the file at /app/config.json and return its contents."},
  {"agent": "server", "task": "Fetch http://example.com/status and return the response."}
]

User: "What time is it and are my blinds working?"
Output: [
  {"agent": "utility", "task": "What is the current time?"},
  {"agent": "home", "task": "Check the status of the blinds."}
]
"""


class PlannerAgent:
    """
    Orchestrator that plans and executes multi-agent workflows.

    Parameters
    ----------
    agents : dict[str, BaseAgent]
        Registry mapping agent name → BaseAgent instance.
    llm_client : AsyncOpenAI
        Pre-constructed async OpenAI-compatible client.
    model : str
        Model identifier string sent to the LLM API.
    """

    def __init__(
        self,
        agents: Dict[str, BaseAgent],
        llm_client: AsyncOpenAI,
        model: str,
    ):
        self.agents = agents
        self.llm_client = llm_client
        self.model = model

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    async def plan(self, task: str) -> List[dict]:
        """
        Ask the LLM to decompose *task* into an ordered list of
        ``{"agent": str, "task": str}`` dicts.

        Falls back to a single utility step if JSON parsing fails.
        """
        try:
            response = await self.llm_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                    {"role": "user", "content": task},
                ],
                temperature=0.0,
            )
            raw = (response.choices[0].message.content or "").strip()

            # Strip accidental markdown fences
            if raw.startswith("```"):
                lines = raw.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                raw = "\n".join(lines).strip()

            plan = json.loads(raw)
            if (
                isinstance(plan, list)
                and all(
                    isinstance(step, dict)
                    and "agent" in step
                    and "task" in step
                    for step in plan
                )
                and len(plan) > 0
            ):
                logger.info(f"PlannerAgent produced {len(plan)} step(s): {plan}")
                return plan

            logger.warning(f"PlannerAgent returned unexpected structure: {plan!r}")
        except json.JSONDecodeError as e:
            logger.warning(f"PlannerAgent JSON parse error: {e}")
        except Exception as e:
            logger.error(f"PlannerAgent plan() failed: {e}")

        # Safe fallback — send everything to the utility agent
        fallback = [{"agent": "utility", "task": task}]
        logger.info(f"PlannerAgent falling back to: {fallback}")
        return fallback

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def run(self, task: str) -> str:
        """
        Plan the task and execute each step with the designated agent.
        Returns a combined result string.
        """
        steps = await self.plan(task)
        results = []

        for step in steps:
            agent_name = step.get("agent", "utility")
            sub_task = step.get("task", task)

            logger.info(f"PlannerAgent → {agent_name}: '{sub_task}'")

            agent = self.agents.get(agent_name)
            if agent is None:
                msg = (
                    f"[PlannerAgent] Agent '{agent_name}' not found in registry. "
                    f"Available agents: {list(self.agents.keys())}. Skipping step."
                )
                logger.error(msg)
                results.append(msg)
                continue

            try:
                result = await agent.run(sub_task)
            except Exception as e:
                result = f"[{agent_name}] Unexpected error: {e}"
                logger.error(f"PlannerAgent: agent '{agent_name}' raised an exception: {e}")

            results.append(result)

        return "\n\n".join(results) if results else "No steps were executed."
