import asyncio
import logging
from event_queue import Event, get_queue
from event_routes import EVENT_ROUTES, find_route

logger = logging.getLogger("EventWorker")


class EventWorker:
    """
    Drains the shared asyncio.Queue and dispatches each Event to the
    appropriate agent (or PlannerAgent).  Calls event.reply_fn with the
    result so the source can send a response back to the user.
    """

    def __init__(self, planner, agents: dict):
        self.planner = planner
        self.agents = agents
        self._running = False

    def _build_task(self, route, event: Event) -> str:
        safe_payload = {k: v for k, v in event.payload.items() if isinstance(k, str)}
        try:
            return route.task_template.format(
                topic=event.topic,
                payload=event.payload,
                text=event.payload.get("text", str(event.payload)),
                **safe_payload,
            )
        except (KeyError, IndexError):
            return route.task_template

    async def _dispatch(self, event: Event):
        route = find_route(event.topic, event.event_type, EVENT_ROUTES)
        if route is None:
            logger.warning(
                f"No route for topic='{event.topic}' type='{event.event_type}' — dropping event."
            )
            return

        task = self._build_task(route, event)
        agent_label = route.agent or "planner"
        logger.info(f"[EventWorker] {event.source} → {agent_label} | task: '{task[:100]}...'")

        try:
            if route.agent:
                agent = self.agents.get(route.agent)
                if not agent:
                    logger.error(
                        f"Agent '{route.agent}' not found. Available: {list(self.agents.keys())}"
                    )
                    result = f"Configuration error: agent '{route.agent}' not found."
                else:
                    result = await agent.run(task)
            else:
                result = await self.planner.run(task)
        except Exception as e:
            logger.error(f"[EventWorker] dispatch error: {e}")
            result = f"Internal error processing event: {e}"

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
