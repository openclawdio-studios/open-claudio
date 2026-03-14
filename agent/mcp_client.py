import asyncio
import json
import logging
from typing import Dict, Any, Callable, List

from mcp import ClientSession
from mcp.client.sse import sse_client

logger = logging.getLogger(__name__)

class DomoticsMCPClient:
    def __init__(self, server_url: str = "http://mcp_domotics:8000/sse"):
        self.server_url = server_url
        self.session: ClientSession | None = None
        self._exit_stack = None
        self._tools_cache = []

    async def connect(self):
        """Connects to the MCP server using SSE."""
        from contextlib import AsyncExitStack
        self._exit_stack = AsyncExitStack()
        
        try:
            sse_transport = await self._exit_stack.enter_async_context(sse_client(self.server_url))
            self.session = await self._exit_stack.enter_async_context(ClientSession(*sse_transport))
            await self.session.initialize()
            logger.info(f"Connected to MCP Server at {self.server_url}")
            
            # Fetch tools on connect
            response = await self.session.list_tools()
            self._tools_cache = response.tools
            logger.info(f"Loaded {len(self._tools_cache)} tools from MCP server.")
            
        except Exception as e:
            logger.error(f"Failed to connect to MCP server at {self.server_url}: {e}")
            if self._exit_stack:
                await self._exit_stack.aclose()
            self.session = None

    async def disconnect(self):
        if self._exit_stack:
            await self._exit_stack.aclose()
            logger.info("Disconnected from MCP Server.")

    def get_available_tools(self) -> List[Any]:
        return self._tools_cache

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """Call a specific tool on the MCP server."""
        if not self.session:
            return f"Error: Not connected to MCP server (tried to call {name})"
        
        try:
            logger.info(f"Calling MCP Tool: {name} with arguments {arguments}")
            result = await self.session.call_tool(name, arguments=arguments)
            # Assuming result.content is a list of TextContent or ImageContent
            texts = [c.text for c in result.content if hasattr(c, 'text')]
            return "\n".join(texts)
        except Exception as e:
            logger.error(f"Error calling MCP tool {name}: {e}")
            return f"Error executing tool {name}: {str(e)}"
