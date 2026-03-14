# Open-Claudio Context & Architecture

This document serves as the primary context for AI agents working on the **Open-Claudio** project. It outlines the current state, architecture, and design decisions to ensure any AI can ramp up quickly.

## Architecture Overview

**Open-Claudio** is a decoupled, Docker-compose orchestrated system consisting of two main services:

### 1. ReAct Agent (`agent/`)
- **Core Loop**: Implements the Reason + Act (ReAct) paradigm. It uses the `openai` python package to communicate with a local LLM Studio instance (currently exposing `gpt-oss-20b` at `http://100.116.250.89:1234/v1`). 
- **Tool Management**: Contains native python tools (like `get_time`, `read_file`) in `agent/tools.py`.
- **MCP Client**: Most importantly, the agent utilizes a dynamic MCP (Model Context Protocol) Client (`mcp_client.py`) using Server-Sent Events (SSE). On startup, it connects to the `mcp_domotics` server and registers its remote tools on-the-fly, mixing them with the local tools before sending the unified tool schema to the LLM.
- **State**: Maintains a simple JSON-based memory (`memory.json`).
- **Base Image**: `alpine:latest` to avoid Docker hub network constraints, with a virtual environment (`/opt/venv`).

### 2. Domotics MCP Server (`mcp_domotics/`)
- **Framework**: Built with `FastMCP` (python).
- **Functionality**: Replaces legacy Node.js scripts (like OpenClaw's `persianas.js`). It acts as a dedicated HTTP integration layer to external IoT network boundaries.
- **Tools Exposed**:
  - `set_blinds_state(room, action)`: Controls individual Z-Wave shutters.
  - `set_all_blinds_state(action)`: Controls all shutters.
- **Base Image**: `alpine:latest`. 

## Docker Networking

The two nodes talk over a bridge network (`claudio-net`):
- `mcp_domotics` listens on `0.0.0.0:8000`.
- `agent` hits `http://mcp_domotics:8000/sse` to initiate the MCP handshake.

## How to Interact

1. **Start the stack**: `docker-compose up --build -d`
2. **Talk to the Agent**: `docker attach open-claudio-agent`
   - The agent runs an interactive shell `main.py` where you can type commands like "Abre las persianas del salón".

## Migrating New Skills (Best Practices)

When porting old OpenClaw skills (e.g. legacy JS scripts):
1. **Do not** add them back to the `agent` container. The agent should remain a pure reasoning engine.
2. **Do** add the tools to `mcp_domotics/server.py` using the `@mcp.tool()` decorator if they are home-automation related.
3. If they belong to a different domain (e.g. Spotify control, File Management), create a *new* MCP Server container and attach it to the `docker-compose.yml`, then update `agent/main.py` to instantiate another `ClientSession` for that new server. MVC/SOA separation of concerns is strictly enforced via MCP.

## Environment Layout
```text
.
├── docker-compose.yml
├── CONTEXT.md                 <- You are here
├── README.md
├── agent/
│   ├── Dockerfile
│   ├── main.py                <- Entrypoint (ReAct Loop)
│   ├── mcp_client.py          <- SSE Connection to MCP Servers
│   ├── memory.json
│   ├── requirements.txt
│   └── tools.py               <- Local/Fallback Tools
└── mcp_domotics/
    ├── Dockerfile
    ├── requirements.txt
    └── server.py              <- FastMCP Server
```
