# Implementation Plan: Hierarchical Agents

**Project:** Open-Claudio
**Date:** 2026-03-15
**Status:** Proposal

---

## 1. Context & Current State

```
Current flow:
User → ExtendedReActAgent → [LOCAL_TOOLS + ALL MCP tools] → Tools
                              (get_time, read_file, http_get,
                               set_blinds_state, set_all_blinds_state,   ← mcp_domotics
                               fermax_open_door, get_fermax_*)            ← mcp_fermax
```

The single agent receives ALL tools in its context every turn. This works today but breaks down as tools grow: the LLM gets noise, routing becomes unreliable, and adding new domains requires touching the core agent.

---

## 2. Target Architecture

```
User
 │
 ▼
PlannerAgent          ← LLM-based router / task decomposer
 │
 ├─ HomeAgent         ← blinds (mcp_domotics) + door (mcp_fermax)
 │   tools: set_blinds_state, set_all_blinds_state, fermax_open_door
 │
 ├─ ServerAgent       ← files, HTTP, future docker/logs tools
 │   tools: read_file, list_files, http_get
 │
 ├─ IntercomAgent     ← Fermax info / history
 │   tools: get_fermax_user_info, get_fermax_device_info, get_fermax_history
 │
 └─ UtilityAgent      ← time, generic lookups
     tools: get_time, http_get
```

**Non-goals (kept unchanged):**
- MCP servers (`mcp_domotics`, `mcp_fermax`) — already the right tool layer.
- `MultiMCPClient` — already multi-server aware.
- `tool_healing.py` — used by all agents as-is.
- Docker / networking — no changes.

---

## 3. New File Structure

```
agent/
├── main.py                   # Updated: wire PlannerAgent, keep CLI loop
├── mcp_client.py             # Unchanged
├── tool_healing.py           # Unchanged
├── tools.py                  # Unchanged
└── agents/
    ├── __init__.py
    ├── base_agent.py         # BaseAgent: ReAct loop + tool_healing
    ├── planner_agent.py      # Routes or decomposes tasks
    ├── home_agent.py         # Blinds + door
    ├── server_agent.py       # Files, HTTP, future server tools
    ├── intercom_agent.py     # Fermax info / history
    └── utility_agent.py      # Time, generic
```

---

## 4. Implementation Steps

### Phase 1 — BaseAgent (refactor, no new behaviour)

Extract the ReAct loop from `ExtendedReActAgent` into `agents/base_agent.py`.

```python
# agents/base_agent.py

class BaseAgent:
    """
    Generic ReAct agent. Receives an explicit tool whitelist at construction.
    Inherits tool_healing from the shared layer.
    """
    def __init__(
        self,
        name: str,
        tool_names: list[str],          # whitelist — only these tools are passed to the LLM
        mcp_client: MultiMCPClient,
        memory: dict,
        llm_client: AsyncOpenAI,
        model: str,
        system_prompt_extra: str = "",
    ):
        self.name = name
        self.tool_names = set(tool_names)
        self.mcp_client = mcp_client
        self.memory = memory            # shared memory dict (namespaced keys)
        self.client = llm_client
        self.model = model
        self.system_prompt_extra = system_prompt_extra

    def _build_tools(self) -> list:
        """Return only the whitelisted subset of available tools."""
        # (same logic as current _build_openai_tools, filtered by self.tool_names)
        ...

    async def run(self, task: str) -> str:
        """Execute a single task using the ReAct loop."""
        # Identical to current process_user_input, uses self._execute_tool
        ...

    async def _execute_tool(self, name: str, arguments: dict) -> str:
        # Delegates to tool_healing functions, same as current code
        ...
```

**Key points:**
- `BaseAgent.run()` is the current `process_user_input()` body — no logic change.
- The only addition is the `tool_names` whitelist filter in `_build_tools()`.
- Memory is shared by reference (all agents read/write the same dict, namespaced).

---

### Phase 2 — Specialized Agents

Each is a thin instantiation of `BaseAgent` with a curated tool list and a domain-specific system prompt.

```python
# agents/home_agent.py

HOME_TOOLS = [
    "set_blinds_state",
    "set_all_blinds_state",
    "fermax_open_door",
]

HOME_PROMPT = """You are the Home Agent for Open-Claudio.
You control physical devices in the house: blinds/shutters and the entrance door intercom.
Use the available tools precisely. Do not use tools outside your domain."""

def make_home_agent(mcp_client, memory, llm_client, model) -> BaseAgent:
    return BaseAgent("home", HOME_TOOLS, mcp_client, memory, llm_client, model, HOME_PROMPT)
```

```python
# agents/server_agent.py

SERVER_TOOLS = ["read_file", "list_files", "http_get"]

SERVER_PROMPT = """You are the Server Agent for Open-Claudio.
You manage files, fetch URLs, and inspect the server environment.
"""
```

```python
# agents/intercom_agent.py

INTERCOM_TOOLS = [
    "get_fermax_user_info",
    "get_fermax_device_info",
    "get_fermax_history",
]
```

```python
# agents/utility_agent.py

UTILITY_TOOLS = ["get_time", "http_get"]
```

---

### Phase 3 — PlannerAgent

The planner does two things:
1. **Route** — simple tasks go to a single agent.
2. **Decompose** — complex tasks (multi-domain) split into an ordered list of sub-tasks.

```python
# agents/planner_agent.py

AGENT_REGISTRY = {
    "home":     HomeAgent,
    "server":   ServerAgent,
    "intercom": IntercomAgent,
    "utility":  UtilityAgent,
}

PLANNER_PROMPT = """
You are the Planner for Open-Claudio, a home automation AI system.

Available agents and their responsibilities:
- home:     blinds/shutters (subir/bajar persianas), door/intercom opening
- server:   files, HTTP requests, server diagnostics
- intercom: Fermax intercom account info, device status, call history
- utility:  current time, generic queries

Your job: given a user task, output a JSON plan — an ordered list of steps.
Each step: {"agent": "<name>", "task": "<specific sub-task string>"}

Rules:
- Simple task → one step.
- Multi-domain task → multiple steps in logical order.
- Output ONLY valid JSON. No explanation. No markdown.

Example:
Task: "prepara la casa para salir y dime la hora"
Output: [
  {"agent": "home", "task": "baja todas las persianas"},
  {"agent": "utility", "task": "dime la hora actual"}
]
"""

class PlannerAgent:
    def __init__(self, agents: dict, llm_client, model):
        self.agents = agents          # name → BaseAgent instance
        self.client = llm_client
        self.model = model

    async def plan(self, task: str) -> list[dict]:
        """Ask the LLM to decompose the task into a list of agent steps."""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": PLANNER_PROMPT},
                {"role": "user",   "content": task},
            ],
            temperature=0.0,
        )
        raw = response.choices[0].message.content or "[]"
        return json.loads(raw)   # list of {"agent": ..., "task": ...}

    async def run(self, task: str) -> str:
        """Plan then execute each step sequentially."""
        steps = await self.plan(task)

        if not steps:
            return "Planner could not determine how to handle this task."

        results = []
        for step in steps:
            agent_name = step.get("agent")
            sub_task   = step.get("task", task)
            agent = self.agents.get(agent_name)

            if not agent:
                results.append(f"[{agent_name}] Unknown agent.")
                continue

            logger.info(f"PlannerAgent → {agent_name}: '{sub_task}'")
            result = await agent.run(sub_task)
            results.append(f"[{agent_name}] {result}")

        return "\n".join(results)
```

---

### Phase 4 — Update main.py

```python
# main.py  (simplified diff)

from agents.base_agent     import BaseAgent
from agents.home_agent     import make_home_agent
from agents.server_agent   import make_server_agent
from agents.intercom_agent import make_intercom_agent
from agents.utility_agent  import make_utility_agent
from agents.planner_agent  import PlannerAgent

class OpenClaudio:
    def __init__(self):
        self.mcp_client = MultiMCPClient(server_urls=MCP_SERVER_URLS)
        self.memory = load_memory()

    async def initialize(self):
        await self.mcp_client.connect()

        shared = dict(mcp_client=self.mcp_client, memory=self.memory,
                      llm_client=client, model=MODEL_NAME)

        agents = {
            "home":     make_home_agent(**shared),
            "server":   make_server_agent(**shared),
            "intercom": make_intercom_agent(**shared),
            "utility":  make_utility_agent(**shared),
        }
        self.planner = PlannerAgent(agents, client, MODEL_NAME)

    async def process(self, user_input: str) -> str:
        return await self.planner.run(user_input)

    async def shutdown(self):
        await self.mcp_client.disconnect()
        save_memory(self.memory)
```

---

## 5. Memory Namespacing

All agents share `memory.json` but use namespaced keys to avoid collision:

```json
{
  "home":     { "tool_fixes": [...], "tool_metrics": {...} },
  "server":   { "tool_fixes": [...], "tool_metrics": {...} },
  "intercom": { "tool_fixes": [...], "tool_metrics": {...} }
}
```

`BaseAgent` reads/writes `self.memory[self.name]` instead of `self.memory` directly. `tool_healing` functions receive this sub-dict.

---

## 6. Example Execution Traces

### Simple task
```
User: "baja todas las persianas"

PlannerAgent.plan() →
  [{"agent": "home", "task": "baja todas las persianas"}]

HomeAgent.run("baja todas las persianas") →
  Tool: set_all_blinds_state(action="off")
  → "OK: Acción 'off' enviada a TODAS las persianas."
```

### Multi-step task
```
User: "prepara la casa para salir"

PlannerAgent.plan() →
  [
    {"agent": "home", "task": "baja todas las persianas"},
    {"agent": "home", "task": "asegúrate de que la puerta está cerrada"}
  ]

Step 1: HomeAgent → set_all_blinds_state(action="off")
Step 2: HomeAgent → (no tool action needed, reports door state)

Final: "[home] Persianas bajadas.\n[home] La puerta ya está cerrada."
```

### Multi-domain task
```
User: "cierra la casa y dime el historial del videoportero"

PlannerAgent.plan() →
  [
    {"agent": "home",     "task": "baja todas las persianas"},
    {"agent": "intercom", "task": "muéstrame el historial reciente del videoportero"}
  ]

Step 1: HomeAgent → set_all_blinds_state(action="off")
Step 2: IntercomAgent → get_fermax_history()
```

---

## 7. Rollout Phases

| Phase | What | Risk | Effort |
|-------|------|------|--------|
| 1 | Extract `BaseAgent` from `ExtendedReActAgent` | Low — pure refactor | Small |
| 2 | Create specialized agent files (thin wrappers) | Low | Small |
| 3 | Implement `PlannerAgent` | Medium — LLM routing quality | Medium |
| 4 | Update `main.py`, wire everything | Low | Small |
| 5 | Memory namespacing | Low | Small |

---

## 8. Design Constraints (inherited from project rules)

- **No tools in the agent.** All new tools continue to go into MCP server files.
- **MCP servers unchanged.** The planner operates above the tool layer, not inside it.
- **Local tools** (`tools.py`) stay local — they are assigned to agents by whitelist, not moved.
- **Single `MultiMCPClient`** — all agents share one connection pool, routing by tool name.

---

## 9. Future Extensions

Once this foundation is in place:

- **`server_agent`** can gain Docker/systemd tools via a new `mcp_server` container.
- **`network_agent`** (ping, port scan) can be added as a new MCP server + new agent, zero changes to existing code.
- **Agent-level RAG**: each agent's system prompt can be augmented with domain-specific retrieval.
- **Parallel execution**: `PlannerAgent` can run independent steps concurrently via `asyncio.gather()`.
- **Self-healing + Hierarchical**: the existing `tool_healing` layer already works per-agent without modification.
