import asyncio
import json
import logging
import os
from openai import AsyncOpenAI
from mcp_client import MultiMCPClient
from agents.home_agent import make_home_agent
from agents.server_agent import make_server_agent
from agents.intercom_agent import make_intercom_agent
from agents.utility_agent import make_utility_agent
from agents.planner_agent import PlannerAgent

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("OpenClaudio")

# Configuration from environment or defaults
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
    Top-level orchestrator for the Open-Claudio hierarchical agent system.

    Lifecycle:
        oc = OpenClaudio()
        await oc.initialize()      # connect MCP, build agents
        result = await oc.process(user_input)
        await oc.shutdown()        # disconnect, save memory
    """

    def __init__(self):
        self.mcp_client = MultiMCPClient(server_urls=MCP_SERVER_URLS)
        self.memory = load_memory()
        self.planner: PlannerAgent = None  # set in initialize()

    async def initialize(self):
        """Connect to all MCP servers and instantiate all agents."""
        logger.info("Connecting to MCP servers...")
        await self.mcp_client.connect()

        logger.info("Instantiating domain agents...")
        home_agent = make_home_agent(self.mcp_client, self.memory, llm_client, MODEL_NAME)
        server_agent = make_server_agent(self.mcp_client, self.memory, llm_client, MODEL_NAME)
        intercom_agent = make_intercom_agent(self.mcp_client, self.memory, llm_client, MODEL_NAME)
        utility_agent = make_utility_agent(self.mcp_client, self.memory, llm_client, MODEL_NAME)

        agents = {
            "home": home_agent,
            "server": server_agent,
            "intercom": intercom_agent,
            "utility": utility_agent,
        }

        self.planner = PlannerAgent(agents=agents, llm_client=llm_client, model=MODEL_NAME)
        logger.info("OpenClaudio initialized with agents: %s", list(agents.keys()))

    async def process(self, user_input: str) -> str:
        """Delegate the user request to the planner."""
        return await self.planner.run(user_input)

    async def shutdown(self):
        """Disconnect from MCP servers and persist memory."""
        await self.mcp_client.disconnect()
        save_memory(self.memory)
        logger.info("OpenClaudio shut down. Memory saved.")


async def main():
    print("Initializing Open-Claudio Hierarchical Agent System...")
    oc = OpenClaudio()
    await oc.initialize()

    print("\nAgent Ready. Type 'exit' to quit.")
    try:
        while True:
            user_in = input("\n>> ")
            if user_in.strip().lower() in ['exit', 'quit']:
                break

            if not user_in.strip():
                continue

            result = await oc.process(user_in)
            print(f"\n[Agent]: {result}")

    finally:
        await oc.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
