import asyncio
import json
import logging
import os
import sys
import time
from openai import AsyncOpenAI
from db import recorder
from mcp_client import MultiMCPClient
from agents.home_agent import make_home_agent
from agents.server_agent import make_server_agent
from agents.intercom_agent import make_intercom_agent
from agents.utility_agent import make_utility_agent
from agents.knowledge_agent import make_knowledge_agent
from agents.planner_agent import PlannerAgent
from event_worker import EventWorker

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("OpenClaudio")

LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "http://100.116.250.89:1234/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-oss-20b")
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")
MCP_SERVER_URLS = os.getenv("MCP_SERVER_URLS", "http://mcp_domotics:8000/sse").split(",")

llm_client = AsyncOpenAI(base_url=LLM_ENDPOINT, api_key=LLM_API_KEY)


def load_memory():
    try:
        with open("memory.json") as f:
            return json.load(f)
    except Exception:
        return {}


def save_memory(memory):
    with open("memory.json", "w") as f:
        json.dump(memory, f, indent=2)


class OpenClaudio:
    """
    Top-level orchestrator for the Open-Claudio hierarchical + event-driven agent system.

    Lifecycle:
        oc = OpenClaudio()
        await oc.initialize()      # connect MCP, build agents
        result = await oc.process(user_input)
        await oc.shutdown()        # disconnect, save memory
    """

    def __init__(self):
        self.mcp_client = MultiMCPClient(server_urls=MCP_SERVER_URLS)
        self.memory = load_memory()
        self.planner: PlannerAgent = None
        self.agents: dict = {}

    async def initialize(self):
        """Connect to all MCP servers, instantiate agents, and init DB recorder."""
        logger.info("Connecting to MCP servers...")
        await self.mcp_client.connect()
        await recorder.init()

        logger.info("Instantiating domain agents...")
        shared = dict(
            mcp_client=self.mcp_client,
            memory=self.memory,
            llm_client=llm_client,
            model=MODEL_NAME,
        )
        self.agents = {
            "home":      make_home_agent(**shared),
            "server":    make_server_agent(**shared),
            "intercom":  make_intercom_agent(**shared),
            "utility":   make_utility_agent(**shared),
            "knowledge": make_knowledge_agent(**shared),
        }
        self.planner = PlannerAgent(agents=self.agents, llm_client=llm_client, model=MODEL_NAME)
        logger.info("OpenClaudio initialized. Agents: %s", list(self.agents.keys()))

    async def process(self, user_input: str, source: str = "cli") -> str:
        """Delegate the user request to the planner, wrapped in a DB trace."""
        t0 = time.monotonic()
        trace_id = await recorder.start_trace(source=source, user_input=user_input)
        recorder.set_trace_id(trace_id) if trace_id else None

        status = "success"
        result = ""
        try:
            result = await self.planner.run(user_input)
            return result
        except Exception as exc:
            status = "error"
            result = str(exc)
            raise
        finally:
            duration_ms = int((time.monotonic() - t0) * 1000)
            await recorder.complete_trace(
                trace_id=trace_id,
                output=result,
                status=status,
                duration_ms=duration_ms,
            )

    async def shutdown(self):
        """Disconnect from MCP servers and persist memory."""
        await self.mcp_client.disconnect()
        save_memory(self.memory)
        logger.info("OpenClaudio shut down. Memory saved.")


def _build_event_tasks(oc: OpenClaudio) -> list:
    """Build background task coroutines for all enabled event sources."""
    tasks = []

    # EventWorker always runs
    worker = EventWorker(planner=oc.planner, agents=oc.agents)
    tasks.append(worker.run())

    # MQTT source — enabled only if MQTT_ENABLED=true (MQTT_HOST is config, not a feature flag)
    if os.getenv("MQTT_ENABLED", "").lower() == "true":
        from sources.mqtt_source import MQTTSource
        tasks.append(MQTTSource().run())
        logger.info("MQTTSource enabled (MQTT_HOST=%s)", os.getenv("MQTT_HOST", "mosquitto"))

    # Telegram source — enabled if TELEGRAM_BOT_TOKEN is set
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        from sources.telegram_source import TelegramSource
        tasks.append(TelegramSource().run())
        logger.info("TelegramSource enabled")

    # HTTP source — enabled if HTTP_EVENT_ENABLED=true
    if os.getenv("HTTP_EVENT_ENABLED", "").lower() == "true":
        from sources.http_source import HTTPSource
        tasks.append(HTTPSource().run())
        logger.info("HTTPSource enabled on port %s", os.getenv("HTTP_EVENT_PORT", "8080"))

    return tasks


async def main():
    print("Initializing Open-Claudio Hierarchical + Event-Driven Agent System...")
    oc = OpenClaudio()
    await oc.initialize()

    # Build and start background event services
    service_tasks = [asyncio.create_task(coro) for coro in _build_event_tasks(oc)]

    active_sources = []
    if os.getenv("MQTT_ENABLED", "").lower() == "true":
        active_sources.append("MQTT")
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        active_sources.append("Telegram")
    if os.getenv("HTTP_EVENT_ENABLED", "").lower() == "true":
        active_sources.append(f"HTTP :{os.getenv('HTTP_EVENT_PORT', '8080')}")

    if active_sources:
        print(f"Event sources active: {', '.join(active_sources)}")

    if sys.stdin.isatty():
        # Interactive CLI mode — only when stdin is truly readable (docker attach / local run)
        print("CLI ready. Type 'exit' to quit.\n")
        loop = asyncio.get_event_loop()
        try:
            while True:
                try:
                    user_in = await loop.run_in_executor(None, input, ">> ")
                except EOFError:
                    # stdin closed (e.g. docker-compose up without attach) — fall back to daemon
                    logger.info("stdin closed — switching to daemon mode.")
                    await asyncio.gather(*service_tasks)
                    break
                if user_in.strip().lower() in ("exit", "quit"):
                    break
                if not user_in.strip():
                    continue
                result = await oc.process(user_in)
                print(f"\n[Agent]: {result}\n")
        finally:
            for task in service_tasks:
                task.cancel()
            await asyncio.gather(*service_tasks, return_exceptions=True)
            await oc.shutdown()
    else:
        # Daemon mode — keep alive waiting for events
        logger.info("Running in daemon mode (no TTY). Waiting for events...")
        try:
            await asyncio.gather(*service_tasks)
        except asyncio.CancelledError:
            pass
        finally:
            await oc.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
