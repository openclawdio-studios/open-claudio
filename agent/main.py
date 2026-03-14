import asyncio
import json
import logging
import os
from openai import AsyncOpenAI
from tools import LOCAL_TOOLS
from mcp_client import MultiMCPClient

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ReActAgent")

# Configuration from environment or defaults
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "http://100.116.250.89:1234/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-oss-20b")
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")
MCP_SERVER_URLS = os.getenv("MCP_SERVER_URLS", "http://mcp_domotics:8000/sse").split(",")
MAX_STEPS = int(os.getenv("MAX_STEPS", "8"))

client = AsyncOpenAI(base_url=LLM_ENDPOINT, api_key=LLM_API_KEY)

def load_memory():
    try:
        with open("memory.json") as f:
            return json.load(f)
    except:
        return {}

def save_memory(memory):
    with open("memory.json", "w") as f:
        json.dump(memory, f, indent=2)

class ExtendedReActAgent:
    def __init__(self):
        self.mcp_client = MultiMCPClient(server_urls=MCP_SERVER_URLS)
        self.memory = load_memory()
        
    async def initialize(self):
        await self.mcp_client.connect()

    async def shutdown(self):
        await self.mcp_client.disconnect()
        save_memory(self.memory)

    def _build_openai_tools(self) -> list:
        tools = []
        # Add local tools
        for name, tool_info in LOCAL_TOOLS.items():
            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool_info["description"],
                    "parameters": tool_info.get("schema", {"type": "object", "properties": {}})
                }
            })
            
        # Add MCP remote tools
        mcp_tools = self.mcp_client.get_available_tools()
        for t in mcp_tools:
            tools.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or f"MCP tool {t.name}",
                    "parameters": t.inputSchema
                }
            })
            
        return tools

    async def _execute_tool(self, name: str, arguments: dict) -> str:
        # Check local tools first
        if name in LOCAL_TOOLS:
            logger.info(f"Executing Local Tool: {name}")
            try:
                fn = LOCAL_TOOLS[name]["function"]
                # Pass arguments directly for simplicity (tools.py design uses kwargs)
                result = fn(**arguments)
                return str(result)
            except Exception as e:
                return f"Error executing local tool {name}: {str(e)}"
                
        # Fallback to MCP tools
        mcp_tools = self.mcp_client.get_available_tools()
        if any(t.name == name for t in mcp_tools):
            return await self.mcp_client.call_tool(name, arguments)
            
        return f"Tool {name} not found."

    async def process_user_input(self, user_input: str) -> str:
        system_prompt = f"""You are 'Open-Claudio', an advanced AI home automation assistant.
You have access to a set of internal and external tools via function calling.
CRITICAL INSTRUCTIONS:
1. You MUST use the provided tools to fulfill the user's request.
2. DO NOT make up or hallucinate states. If the user asks you to open a blind or a door, YOU MUST CALL THE CORRESPONDING FUNCTION.
3. If the user asks about Fermax devices, call `get_fermax_device_info` or `fermax_open_door`.
4. If the user asks about Domotics or blinds (persianas), call `open_blinds` or `set_blinds_state`.
5. Only reply directly without tool calls if you are just carrying out normal conversation.

User Memory Context: {json.dumps(self.memory)}
"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]
        
        tools = self._build_openai_tools()
        logger.debug(f"Sending {len(tools)} tools to LLM: {[t['function']['name'] for t in tools]}")
        
        for step in range(MAX_STEPS):
            logger.info(f"--- Step {step+1}/{MAX_STEPS} ---")
            
            try:
                # Only pass tool_choice if tools are present
                kwargs = {
                    "model": MODEL_NAME,
                    "messages": messages,
                    "temperature": 0.2
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"
                    
                response = await client.chat.completions.create(**kwargs)
            except Exception as e:
                logger.error(f"LLM Call failed: {e}")
                return f"Error communicating with LLM: {str(e)}"
                
            message = response.choices[0].message
            messages.append(message)
            
            # Check if there are tool calls to make
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    fn_name = tool_call.function.name
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except:
                        args = {}
                    
                    logger.info(f"LLM requested tool call: {fn_name}({args})")
                    
                    observation = await self._execute_tool(fn_name, args)
                    logger.info(f"Tool Result: {observation[:200]}...")
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(observation)
                    })
            else:
                # No tool calls, the LLM has given us a final answer
                return message.content

        return "Max reasoning steps reached without final answer."

async def main():
    print("Initializing Open-Claudio ReAct Agent...")
    agent = ExtendedReActAgent()
    await agent.initialize()
    
    print("\nAgent Ready. Type 'exit' to quit.")
    try:
        while True:
            user_in = input("\n>> ")
            if user_in.strip().lower() in ['exit', 'quit']:
                break
                
            if not user_in.strip():
                continue
                
            result = await agent.process_user_input(user_in)
            print(f"\n[Agent]: {result}")
            
    finally:
        await agent.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
