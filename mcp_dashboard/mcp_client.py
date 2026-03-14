import asyncio
import logging
from typing import Dict, Any, List

from mcp import ClientSession
from mcp.client.sse import sse_client

logger = logging.getLogger("dashboard_mcp_client")

class MultiMCPClient:
    def __init__(self, server_urls: List[str]):
        self.server_urls = server_urls
        self.connections: Dict[str, Dict[str, Any]] = {}

    async def connect(self):
        for url in self.server_urls:
            url = url.strip()
            if not url:
                continue
                
            logger.info(f"Attempting connection to MCP Server at {url}")
            from contextlib import asynccontextmanager
            import asyncio
            
            # Retry up to 5 times (total 10 seconds wait)
            for attempt in range(5):
                try:
                    sse_ctx = sse_client(url)
                    sse_transport = await sse_ctx.__aenter__()
                    
                    session_ctx = ClientSession(*sse_transport)
                    session = await session_ctx.__aenter__()
                    
                    await session.initialize()
                    response = await session.list_tools()
                    tools = response.tools
                    
                    self.connections[url] = {
                        "session": session,
                        "session_ctx": session_ctx,
                        "sse_ctx": sse_ctx,
                        "tools": tools
                    }
                    logger.info(f"Successfully connected to {url} on attempt {attempt+1}")
                    break # Success, break retry loop
                except Exception as e:
                    logger.error(f"Attempt {attempt+1} failed to connect to MCP server at {url}: {e}")
                    if attempt < 4:
                        await asyncio.sleep(2)

    async def disconnect(self):
        for url, conn in self.connections.items():
            if "session_ctx" in conn:
                try:
                    await conn["session_ctx"].__aexit__(None, None, None)
                except Exception as e:
                    pass
            if "sse_ctx" in conn:
                try:
                    await conn["sse_ctx"].__aexit__(None, None, None)
                except Exception as e:
                    pass
        self.connections.clear()

    def get_available_tools(self) -> List[dict]:
        all_tools = []
        for url, conn in self.connections.items():
            for t in conn.get("tools", []):
                all_tools.append({
                    "server": url,
                    "name": t.name,
                    "description": t.description,
                    "schema": t.inputSchema
                })
        return all_tools

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        for url, conn in self.connections.items():
            session: ClientSession = conn.get("session")
            tools = conn.get("tools", [])
            
            if any(t.name == name for t in tools):
                try:
                    result = await session.call_tool(name, arguments=arguments)
                    texts = [c.text for c in result.content if hasattr(c, 'text')]
                    return "\n".join(texts)
                except Exception as e:
                    return f"Error executing tool {name} remotely: {str(e)}"
                    
        return f"Error: Tool '{name}' not found."
