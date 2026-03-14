import asyncio
import json
import logging
from typing import Dict, Any, List

from mcp import ClientSession
from mcp.client.sse import sse_client
from contextlib import AsyncExitStack

logger = logging.getLogger("mcp_client")

class MultiMCPClient:
    def __init__(self, server_urls: List[str]):
        """
        Initializes a client capable of connecting to multiple MCP servers simultaneously.
        """
        self.server_urls = server_urls
        # Maps server_url -> dict with connection state
        self.connections: Dict[str, Dict[str, Any]] = {}

    async def connect(self):
        """Connects to all configured MCP servers."""
        for url in self.server_urls:
            url = url.strip()
            if not url:
                continue
                
            logger.info(f"Attempting connection to MCP Server at {url}")
            try:
                # We manage the contexts manually to avoid AsyncExitStack issues on some Python/AnyIO versions.
                from contextlib import asynccontextmanager
                
                sse_ctx = sse_client(url)
                sse_transport = await sse_ctx.__aenter__()
                
                session_ctx = ClientSession(*sse_transport)
                session = await session_ctx.__aenter__()
                
                await session.initialize()
                
                # Fetch tools on connect
                response = await session.list_tools()
                tools = response.tools
                
                logger.info(f"Successfully connected to {url}. Loaded {len(tools)} tools.")
                
                self.connections[url] = {
                    "session": session,
                    "session_ctx": session_ctx,
                    "sse_ctx": sse_ctx,
                    "tools": tools
                }
            except Exception as e:
                logger.error(f"Failed to connect to MCP server at {url}: {e}")

    async def disconnect(self):
        """Disconnects from all servers."""
        for url, conn in self.connections.items():
            if "session_ctx" in conn:
                try:
                    await conn["session_ctx"].__aexit__(None, None, None)
                except Exception as e:
                    logger.error(f"Error closing session to {url}: {e}")
            if "sse_ctx" in conn:
                try:
                    await conn["sse_ctx"].__aexit__(None, None, None)
                except Exception as e:
                    logger.error(f"Error closing sse transport to {url}: {e}")
            logger.info(f"Disconnected from MCP Server at {url}")
        self.connections.clear()

    def get_available_tools(self) -> List[Any]:
        """Returns a flat list of all tools from all connected servers."""
        all_tools = []
        for conn in self.connections.values():
            all_tools.extend(conn.get("tools", []))
        return all_tools

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """Finds which server owns the tool and calls it."""
        for url, conn in self.connections.items():
            session: ClientSession = conn.get("session")
            tools = conn.get("tools", [])
            
            # Check if this server has the requested tool
            if any(t.name == name for t in tools):
                try:
                    logger.info(f"Routing call for '{name}' to {url} with args {arguments}")
                    result = await session.call_tool(name, arguments=arguments)
                    # Extract the text content from the MCP protocol response
                    texts = [c.text for c in result.content if hasattr(c, 'text')]
                    return "\n".join(texts)
                except Exception as e:
                    logger.error(f"Error calling MCP tool '{name}' on {url}: {e}")
                    return f"Error executing tool {name} remotely: {str(e)}"
                    
        return f"Error: Tool '{name}' not found on any connected MCP server."
