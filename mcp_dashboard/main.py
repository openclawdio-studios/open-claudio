import os
import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Dict, Any

from mcp_client import MultiMCPClient

app = FastAPI(title="Open-Claudio MCP Dashboard")

# Ensure templates directory exists
os.makedirs("templates", exist_ok=True)
templates = Jinja2Templates(directory="templates")

MCP_SERVER_URLS = os.getenv("MCP_SERVER_URLS", "http://mcp_domotics:8000/sse,http://mcp_fermax:8001/sse").split(",")
mcp_client = MultiMCPClient(server_urls=MCP_SERVER_URLS)

@app.on_event("startup")
async def startup_event():
    await mcp_client.connect()

@app.on_event("shutdown")
async def shutdown_event():
    await mcp_client.disconnect()

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    tools = mcp_client.get_available_tools()
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "tools": tools,
        "servers": MCP_SERVER_URLS
    })

class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]

@app.post("/api/call_tool")
async def call_tool_api(request: ToolCallRequest):
    result = await mcp_client.call_tool(request.tool_name, request.arguments)
    return {"result": result}
