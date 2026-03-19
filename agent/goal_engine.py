"""
GoalEngine — autonomous goal monitoring loop.

Runs as an asyncio background task. Every POLL_INTERVAL seconds it:
  1. Fetches all active goals from the GoalStore, sorted by dynamic priority.
  2. For each goal, checks is_goal_satisfied() against ctx.state.
  3. If not satisfied (or state unknown), publishes an Event so the
     EventWorker drives the planner — GoalEngine NEVER calls the planner directly.

Design rules:
  - GoalEngine is READ-ONLY on the plan/execution pipeline.
  - It only writes to the GoalStore (status bookkeeping).
  - ALL LLM/planner calls happen exclusively inside EventWorker.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from event_queue import Event, get_queue
from goal import GoalStore, Goal, STATUS_DONE, STATUS_FAILED, STATUS_ACTIVE

if TYPE_CHECKING:
    from context import AgentContext

logger = logging.getLogger("GoalEngine")

# How often the engine checks active goals (seconds)
POLL_INTERVAL = 5

# Minimum seconds between re-publishing the same goal (throttle)
_MIN_REFIRE_INTERVAL = 10

# Event type constant consumed by EventWorker
GOAL_EXECUTION_EVENT_TYPE = "goal_execution"


class GoalEngine:
    """
    Autonomous loop that publishes goal_execution events for unsatisfied goals.

    Parameters
    ----------
    goal_store : GoalStore
        The shared goal registry.
    ctx : AgentContext
        Shared context — reads ctx.state for goal satisfaction checks.
    """

    def __init__(self, goal_store: GoalStore, ctx: "AgentContext"):
        self.goal_store = goal_store
        self.ctx = ctx
        self._running = False
        # Track when each goal was last published → throttle
        self._last_fired: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Goal satisfaction check
    # ------------------------------------------------------------------

    def is_goal_satisfied(self, goal: Goal) -> bool:
        """
        Return True only if EVERY key in desired_state matches ctx.state.

        Unknown state (key absent in cache) → return False.
        This means: unknown = not satisfied = try to execute.
        The execution will update the state cache via events.
        """
        if not goal.desired_state:
            # No desired state defined → treat as always satisfied (noop goal)
            logger.debug(f"Goal '{goal.id}' has no desired_state, marking done.")
            return True

        for key, desired_val in goal.desired_state.items():
            current = self.ctx.state.get(key)
            if current is None:
                logger.debug(
                    f"Goal '{goal.id}': state key '{key}' unknown → not satisfied"
                )
                return False
            if current != desired_val:
                logger.debug(
                    f"Goal '{goal.id}': '{key}' is '{current}', want '{desired_val}' → not satisfied"
                )
                return False

        return True

    # ------------------------------------------------------------------
    # Event publishing
    # ------------------------------------------------------------------

    def _should_fire(self, goal: Goal) -> bool:
        """Throttle: don't re-publish a goal more often than _MIN_REFIRE_INTERVAL."""
        last = self._last_fired.get(goal.id, 0)
        return (time.time() - last) >= _MIN_REFIRE_INTERVAL

    async def _publish_goal_event(self, goal: Goal) -> None:
        """Enqueue a goal_execution event for the EventWorker to handle."""
        queue = get_queue()
        event = Event(
            source="goal_engine",
            event_type=GOAL_EXECUTION_EVENT_TYPE,
            topic=GOAL_EXECUTION_EVENT_TYPE,
            payload={"goal_id": goal.id},
            metadata={"priority": goal.compute_priority()},
        )
        await queue.put(event)
        self._last_fired[goal.id] = time.time()
        logger.info(
            f"GoalEngine: published goal_execution for '{goal.id}' "
            f"(priority={goal.compute_priority():.2f})"
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        """Single evaluation pass over all active goals."""
        goals = self.goal_store.list_active()

        if not goals:
            return

        for goal in goals:
            try:
                if self.is_goal_satisfied(goal):
                    goal.status = STATUS_DONE
                    self.goal_store.update(goal)
                    self.goal_store.save()
                    logger.info(f"GoalEngine: goal '{goal.id}' is satisfied → DONE")
                    continue

                if goal.status != STATUS_ACTIVE:
                    goal.status = STATUS_ACTIVE
                    self.goal_store.update(goal)

                if not self._should_fire(goal):
                    logger.debug(
                        f"GoalEngine: throttling goal '{goal.id}' "
                        f"(fired {time.time() - self._last_fired.get(goal.id, 0):.1f}s ago)"
                    )
                    continue

                # Mark bootstrap attempted on first fire
                if not goal.bootstrap_attempted:
                    goal.bootstrap_attempted = True
                    self.goal_store.update(goal)

                await self._publish_goal_event(goal)

            except Exception as e:
                logger.error(f"GoalEngine: error processing goal '{goal.id}': {e}")

    async def run(self) -> None:
        """Continuous loop — runs until stopped."""
        self._running = True
        logger.info(f"GoalEngine started (poll interval={POLL_INTERVAL}s)")

        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"GoalEngine tick error: {e}")

            await asyncio.sleep(POLL_INTERVAL)

    def stop(self) -> None:
        self._running = False
        logger.info("GoalEngine stopped.")
