import asyncio
import json
import logging
import os
from openai import AsyncOpenAI
from tools import LOCAL_TOOLS
from mcp_client import MultiMCPClient
from tool_healing import (
    parse_tool_result, get_strategy, build_repair_prompt, parse_llm_fix,
    lookup_known_fix, record_fix, record_metric, MAX_HEAL_RETRIES,
)

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

    async def _raw_execute_tool(self, name: str, arguments: dict) -> str:
        """Execute a tool without healing — returns raw result string."""
        # Check local tools first
        if name in LOCAL_TOOLS:
            logger.info(f"Executing Local Tool: {name}")
            try:
                fn = LOCAL_TOOLS[name]["function"]
                result = fn(**arguments)
                return str(result)
            except Exception as e:
                return f"Error executing local tool {name}: {str(e)}"
                
        # Fallback to MCP tools
        mcp_tools = self.mcp_client.get_available_tools()
        if any(t.name == name for t in mcp_tools):
            return await self.mcp_client.call_tool(name, arguments)

        # Tool not found — return structured error with available tools list
        all_tool_names = list(LOCAL_TOOLS.keys()) + [t.name for t in mcp_tools]
        return json.dumps({
            "status": "error",
            "error_type": "tool_not_found",
            "message": f"Tool '{name}' not found.",
            "available_tools": all_tool_names
        })

    async def _execute_tool(self, name: str, arguments: dict) -> str:
        """Execute a tool with self-healing: retry, LLM param correction, and fix memory."""
        original_arguments = dict(arguments)

        # Step 1: Apply known fix from memory if available
        fixed_args = lookup_known_fix(self.memory, name, arguments)
        if fixed_args is not None:
            logger.info(f"Applying known fix for '{name}': {arguments} → {fixed_args}")
            arguments = fixed_args

        # Step 2: Execute and parse
        raw = await self._raw_execute_tool(name, arguments)
        result = parse_tool_result(raw)
        record_metric(self.memory, name, result.success, result.error_type)

        if result.success:
            return result.content

        # Step 3: Determine strategy
        strategy = get_strategy(result.error_type)
        logger.warning(f"Tool '{name}' failed (type={result.error_type}, strategy={strategy}): {result.content}")

        # --- Strategy: retry (for connection/timeout errors) ---
        if strategy in ("retry", "retry_then_report"):
            for attempt in range(1, MAX_HEAL_RETRIES + 1):
                logger.info(f"Retry {attempt}/{MAX_HEAL_RETRIES} for '{name}'")
                await asyncio.sleep(1.5 * attempt)  # backoff
                raw = await self._raw_execute_tool(name, arguments)
                result = parse_tool_result(raw)
                record_metric(self.memory, name, result.success, result.error_type)
                if result.success:
                    return result.content
            # Exhausted retries
            return f"Tool '{name}' failed after {MAX_HEAL_RETRIES} retries: {result.content}"

        # --- Strategy: llm_fix (for validation errors) ---
        if strategy == "llm_fix":
            repair_prompt = build_repair_prompt(name, arguments, result)
            logger.info(f"Requesting LLM to fix params for '{name}'")
            try:
                fix_response = await client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[{"role": "user", "content": repair_prompt}],
                    temperature=0.0,
                )
                fix_text = fix_response.choices[0].message.content or ""
                new_args = parse_llm_fix(fix_text)

                if new_args and new_args != arguments:
                    logger.info(f"LLM suggested fix: {arguments} → {new_args}")
                    raw = await self._raw_execute_tool(name, new_args)
                    result = parse_tool_result(raw)
                    record_metric(self.memory, name, result.success, result.error_type)
                    if result.success:
                        # Record the fix for future use and persist immediately
                        record_fix(self.memory, name, original_arguments, new_args)
                        save_memory(self.memory)
                        return result.content
                    else:
                        return f"Tool '{name}' still failed after LLM correction: {result.content}"
                else:
                    logger.warning("LLM could not suggest a valid fix.")
            except Exception as e:
                logger.error(f"LLM fix call failed: {e}")

        # --- Strategy: report (permission errors, tool_not_found, unrecoverable) ---
        # Include available tools hint for tool_not_found so the LLM can self-correct
        if result.error_type == "tool_not_found" and result.raw and isinstance(result.raw, dict):
            avail = result.raw.get("available_tools", [])
            if avail:
                return (f"Tool '{name}' does not exist. "
                        f"Available tools: {', '.join(avail)}. "
                        f"Please use one of the available tools instead.")
        return f"Tool '{name}' error ({result.error_type}): {result.content}"

    async def process_user_input(self, user_input: str) -> str:
        # Build dynamic tool list for the system prompt (no hardcoded names)
        tools = self._build_openai_tools()
        tool_names = [t['function']['name'] for t in tools]
        tool_list_str = ", ".join(f"`{n}`" for n in tool_names)

        # Only send user-facing memory to the LLM (not internal healing data)
        llm_memory = {k: v for k, v in self.memory.items()
                      if k not in ("tool_fixes", "tool_metrics")}

        system_prompt = f"""You are 'Open-Claudio', an advanced AI home automation assistant.
You have access to a set of internal and external tools via function calling.
CRITICAL INSTRUCTIONS:
1. You MUST use the provided tools to fulfill the user's request.
2. DO NOT make up or hallucinate tool names. ONLY use tools from the available list.
3. Available tools: {tool_list_str}
4. If the user asks about blinds/persianas, use the relevant blind control tool from the available list.
5. If the user asks about opening the door/intercom, use the relevant door tool from the available list.
6. Only reply directly without tool calls if you are just carrying out normal conversation.

User Memory Context: {json.dumps(llm_memory)}
"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]
        
        logger.info(f"Sending {len(tools)} tools to LLM: {tool_names}")
        
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
