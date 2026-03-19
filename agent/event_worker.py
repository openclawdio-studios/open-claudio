import asyncio
import logging
import time
from event_queue import Event, get_queue
from event_routes import EVENT_ROUTES, find_route
from goal import GoalStore, STATUS_ACTIVE, STATUS_FAILED
from goal_engine import GOAL_EXECUTION_EVENT_TYPE
from db import recorder

logger = logging.getLogger("EventWorker")

# Replanning thresholds
_REPLAN_THRESHOLD = 2    # fail_count at which we ask the planner for a fresh plan
_FAIL_THRESHOLD = 3      # fail_count at which goal is marked failed


class EventWorker:
    """
    Drains the shared asyncio.Queue and dispatches each Event to the
    appropriate agent (or PlannerAgent).  Calls event.reply_fn with the
    result so the source can send a response back to the user.

    Special path: events with event_type=="goal_execution" bypass the
    normal routing table and are handled by _handle_goal_event().
    """

    def __init__(self, planner, agents: dict, goal_store: GoalStore):
        self.planner = planner
        self.agents = agents
        self.goal_store = goal_store
        self._running = False

    def _build_task(self, route, event: Event) -> str:
        # Build kwargs with defaults first, then let payload keys override — no duplicates
        kwargs = {
            "topic": event.topic,
            "payload": event.payload,
            "text": event.payload.get("text", str(event.payload)),
        }
        kwargs.update({k: v for k, v in event.payload.items() if isinstance(k, str)})
        try:
            return route.task_template.format(**kwargs)
        except (KeyError, IndexError):
            return route.task_template

    # ------------------------------------------------------------------
    # Goal execution path (special — always goes to planner)
    # ------------------------------------------------------------------

    async def _handle_goal_event(self, event: Event) -> str:
        """
        Execute a single goal: plan_from_goal → execute DAG → update goal state.

        Replanning logic:
          fail_count == 0 or 1 → retry same plan (Executor healing covers step-level)
          fail_count == _REPLAN_THRESHOLD → generate a fresh plan
          fail_count > _FAIL_THRESHOLD   → mark goal as failed, stop retrying
        """
        goal_id = event.payload.get("goal_id")
        if not goal_id:
            logger.error("[EventWorker] goal_execution event missing goal_id")
            return "Error: goal_id missing in event payload"

        goal = self.goal_store.get(goal_id)
        if goal is None:
            logger.error(f"[EventWorker] goal '{goal_id}' not found in store")
            return f"Error: goal '{goal_id}' not found"

        if goal.status == STATUS_FAILED:
            logger.info(f"[EventWorker] goal '{goal_id}' already failed, skipping")
            return f"Goal '{goal_id}' is marked as failed."

        # Guard: too many failures → mark failed
        if goal.fail_count > _FAIL_THRESHOLD:
            goal.status = STATUS_FAILED
            self.goal_store.update(goal)
            self.goal_store.save()
            logger.warning(
                f"[EventWorker] goal '{goal_id}' exceeded failure threshold "
                f"({goal.fail_count} failures) → FAILED"
            )
            return f"Goal '{goal_id}' marked as failed after {goal.fail_count} consecutive failures."

        goal.attempts += 1
        goal.status = STATUS_ACTIVE
        self.goal_store.update(goal)

        logger.info(
            f"[EventWorker] executing goal '{goal_id}' "
            f"(attempt={goal.attempts}, fail_count={goal.fail_count})"
        )

        # Choose planning mode based on failure history
        try:
            if goal.fail_count >= _REPLAN_THRESHOLD:
                logger.info(
                    f"[EventWorker] goal '{goal_id}': fail_count={goal.fail_count} → full replan"
                )
                # Fresh plan: describe goal as plain text so planner starts clean
                task = (
                    f"Goal (retry #{goal.attempts}): {goal.description}. "
                    f"Previous attempts failed. Try a different approach."
                )
                result = await self.planner.run(task)
            else:
                # Goal-oriented plan using desired_state vs current ctx.state
                steps = await self.planner.plan_from_goal(goal)
                if not steps:
                    # plan_from_goal returns [] when goal is already satisfied
                    logger.info(f"[EventWorker] goal '{goal_id}' satisfied mid-execution → DONE")
                    from goal import STATUS_DONE
                    goal.status = STATUS_DONE
                    goal.fail_count = 0
                    self.goal_store.update(goal)
                    self.goal_store.save()
                    return f"Goal '{goal_id}' is already satisfied."
                result = await self.planner._execute_dag(steps)
                # Combine results for logging / return
                result = "\n\n".join(result.values()) if isinstance(result, dict) else str(result)

            # Execution succeeded → reset failure counter
            goal.fail_count = 0
            self.goal_store.update(goal)
            self.goal_store.save()
            return result

        except Exception as e:
            goal.fail_count += 1
            self.goal_store.update(goal)
            self.goal_store.save()
            logger.error(
                f"[EventWorker] goal '{goal_id}' execution error "
                f"(fail_count now {goal.fail_count}): {e}"
            )
            return f"Goal '{goal_id}' execution error: {e}"

    # ------------------------------------------------------------------
    # Standard event dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self, event: Event):
        t0 = time.monotonic()

        # --- Special path: goal_execution events bypass routing table ---
        if event.event_type == GOAL_EXECUTION_EVENT_TYPE:
            event_id = await recorder.record_event(
                source=event.source,
                event_type=event.event_type,
                topic=event.topic,
                payload=event.payload if isinstance(event.payload, dict) else {"raw": str(event.payload)},
                metadata=event.metadata if isinstance(event.metadata, dict) else {},
                route_matched="goal_execution",
            )
            goal_id = event.payload.get("goal_id", "unknown")
            trace_id = await recorder.start_trace(
                source="goal_engine", user_input=f"goal:{goal_id}"
            )
            recorder.set_trace_id(trace_id) if trace_id else None
            status = "success"
            result = ""
            try:
                result = await self._handle_goal_event(event)
                return
            except Exception as e:
                result = str(e)
                status = "error"
                logger.error(f"[EventWorker] goal event error: {e}")
            finally:
                duration_ms = int((time.monotonic() - t0) * 1000)
                await recorder.complete_trace(
                    trace_id=trace_id, output=result, status=status, duration_ms=duration_ms
                )
                await recorder.complete_event(event_id, trace_id, duration_ms)
            return

        # --- Normal path ---
        route = find_route(event.topic, event.event_type, EVENT_ROUTES)
        route_name = route.description if route else None

        # Record the incoming event immediately (trace_id filled in later)
        event_id = await recorder.record_event(
            source=event.source,
            event_type=event.event_type,
            topic=event.topic,
            payload=event.payload if isinstance(event.payload, dict) else {"raw": str(event.payload)},
            metadata=event.metadata if isinstance(event.metadata, dict) else {},
            route_matched=route_name,
        )

        if route is None:
            logger.warning(
                f"No route for topic='{event.topic}' type='{event.event_type}' — dropping event."
            )
            return

        task = self._build_task(route, event)
        agent_label = route.agent or "planner"
        logger.info(f"[EventWorker] {event.source} → {agent_label} | task: '{task[:100]}...'")

        # Create a trace for this event (propagate user_id if present in metadata)
        user_id = event.metadata.get("user_id") if isinstance(event.metadata, dict) else None
        trace_id = await recorder.start_trace(source=event.source, user_input=task, user_id=user_id)
        recorder.set_trace_id(trace_id) if trace_id else None

        status = "success"
        result = ""
        try:
            if route.agent:
                agent = self.agents.get(route.agent)
                if not agent:
                    logger.error(
                        f"Agent '{route.agent}' not found. Available: {list(self.agents.keys())}"
                    )
                    result = f"Configuration error: agent '{route.agent}' not found."
                    status = "error"
                else:
                    result = await agent.run(task)
            else:
                result = await self.planner.run(task)
        except Exception as e:
            logger.error(f"[EventWorker] dispatch error: {e}")
            result = f"Internal error processing event: {e}"
            status = "error"
        finally:
            duration_ms = int((time.monotonic() - t0) * 1000)
            await recorder.complete_trace(
                trace_id=trace_id,
                output=result,
                status=status,
                duration_ms=duration_ms,
            )
            await recorder.complete_event(event_id, trace_id, duration_ms)

        logger.info(f"[EventWorker] result: {result[:200]}")

        if event.reply_fn:
            try:
                await event.reply_fn(result)
            except Exception as e:
                logger.error(f"[EventWorker] reply_fn failed: {e}")

    async def run(self):
        queue = get_queue()
        self._running = True
        logger.info("EventWorker started.")
        while self._running:
            try:
                event: Event = await asyncio.wait_for(queue.get(), timeout=1.0)
                # Process one event at a time (sequential) to avoid parallel LLM calls
                await self._dispatch(event)
                queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"EventWorker loop error: {e}")

    def stop(self):
        self._running = False
