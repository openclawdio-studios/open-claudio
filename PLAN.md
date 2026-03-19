# Plan de Mejoras Open-Claudio

> Estado: EN PROGRESO
> Decisiones clave: Executor full separation, AgentContext con services+scratchpad, DAG parallelization, Dynamic tools con candidate system, Capability model light, MCP metadata light, Data collection (no RL aún)

---

## Fase 1 — Executor Separation ✅

**Objetivo:** Separar razonamiento (BaseAgent) de ejecución (Executor). BaseAgent solo llama a LLM y decide; Executor se encarga de healing, retry, MCP dispatch y métricas.

**Archivos afectados:**
- NEW `agent/executor.py` — clase `Executor`
- MOD `agent/agents/base_agent.py` — eliminar toda lógica de tool execution
- MOD `agent/tool_healing.py` — pasa a ser usado internamente por Executor
- MOD `agent/main.py` — instanciar Executor, pasarlo a agentes
- MOD `agent/agents/{home,server,intercom,utility,knowledge}_agent.py` — factories aceptan `executor` en lugar de `mcp_client + memory`

**Diseño:**
```python
class Executor:
    def __init__(self, mcp_client, llm_client, model, memory, recorder): ...
    async def execute(self, agent_name: str, tool_name: str, arguments: dict) -> ToolResult:
        # 1. lookup known fix
        # 2. raw execute (local or MCP)
        # 3. on error → classify → retry / llm_fix / report
        # 4. record metrics
        # 5. record_tool_call()

class BaseAgent:
    def __init__(self, name, tool_names, executor, llm_client, model, system_prompt_extra): ...
    # _react_loop solo: build_tools + LLM calls + executor.execute()
    # Sin referencias a mcp_client, memory, tool_healing
```

**Test mínimo:** Verificar que `BaseAgent` no importa `mcp_client` ni `tool_healing`. Ejecutar un tool simple via `Executor.execute()` con mock MCP.

---

## Fase 2 — AgentContext ✅

**Objetivo:** Objeto de contexto unificado que agrupa services + scratchpad. Todos los agentes lo reciben en lugar de parámetros sueltos.

**Archivos afectados:**
- NEW `agent/context.py` — dataclass `AgentContext`
- MOD `agent/agents/base_agent.py` — recibe `AgentContext`
- MOD `agent/executor.py` — accede a services vía context
- MOD `agent/agents/planner_agent.py` — recibe context
- MOD `agent/main.py` — crea context, lo pasa a todo
- MOD todas las factories

**Diseño:**
```python
@dataclass
class AgentContext:
    # Services
    mcp_client: MultiMCPClient
    llm_client: AsyncOpenAI
    model: str
    executor: Executor

    # Scratchpad (persiste a disco como memory.json actual)
    memory: Dict[str, Any]       # namespaced por agent_name
    history: List[Dict]          # historial de conversación cross-agent
    events: List[Any]            # eventos recientes procesados

    def agent_memory(self, name: str) -> Dict:
        return self.memory.setdefault(name, {})
```

**Persistencia:** `AgentContext.save()` / `load()` serializa solo scratchpad (memory+history) a `memory.json`. Services se reinician en cada sesión.

**Test mínimo:** Context se pasa correctamente, `agent_memory()` mantiene namespacing igual que antes, `memory.json` se carga/guarda correctamente.

---

## Fase 3 — Capability Model (light) ✅

**Objetivo:** Añadir `capabilities` a tools y agentes. El planner usa capabilities para routing en lugar de solo nombres de agentes en el prompt.

**Archivos afectados:**
- MOD `agent/tools.py` — añadir `capabilities` a cada tool
- MOD `agent/mcp_client.py` — propagar capabilities de tools MCP
- MOD `agent/agents/{home,server,intercom,utility,knowledge}_agent.py` — añadir `capabilities` al config
- MOD `agent/agents/planner_agent.py` — construir índice capability→agent, usarlo en prompt y routing

**Diseño:**
```python
# tools.py
LOCAL_TOOLS = {
    "get_time": {
        "capabilities": ["utility", "time"],
        ...
    }
}

# agent config (ej. home_agent.py)
HOME_CONFIG = {
    "name": "home",
    "capabilities": ["home_automation", "blinds", "door_control"],
    "tools": HOME_TOOLS,
    "prompt": HOME_PROMPT,
}

# PlannerAgent: construye índice en __init__
self._capability_index: Dict[str, str] = {}  # capability → agent_name
```

**Cambio en planner prompt:** en lugar de listar agentes con descripciones largas, lista capabilities. Más preciso, prompt más corto.

**Test mínimo:** Tarea "abrir las persianas" llega al home agent vía capability `blinds`, sin que el prompt mencione explícitamente al agente.

---

## Fase 4 — Structured Planner + DAG Parallelization ✅

**Objetivo:** El planner genera planes estructurados con `reason`, `priority` y `depends_on`. La ejecución usa un DAG: pasos sin dependencias corren en paralelo con `asyncio.gather`.

**Archivos afectados:**
- MOD `agent/agents/planner_agent.py` — nuevo formato de plan + ejecución DAG

**Nuevo formato de plan:**
```json
[
  {"id": "s0", "agent": "utility", "task": "obtener hora actual", "reason": "contexto temporal", "priority": 1, "depends_on": []},
  {"id": "s1", "agent": "home",    "task": "abrir persianas salon", "reason": "rutina mañana", "priority": 2, "depends_on": []},
  {"id": "s2", "agent": "home",    "task": "abrir persianas dorm",  "reason": "rutina mañana", "priority": 2, "depends_on": []},
  {"id": "s3", "agent": "server",  "task": "registrar log rutina",  "reason": "auditoría",    "priority": 3, "depends_on": ["s0", "s1", "s2"]}
]
```

**Ejecución DAG:**
```python
async def _execute_dag(self, steps) -> Dict[str, str]:
    results = {}
    pending = list(steps)
    while pending:
        ready = [s for s in pending if all(d in results for d in s["depends_on"])]
        if not ready:
            break  # cycle o fallo de dependencia
        batch_results = await asyncio.gather(*[self._run_step(s) for s in ready], return_exceptions=True)
        for step, result in zip(ready, batch_results):
            results[step["id"]] = str(result)
            pending.remove(step)
    return results
```

**Test mínimo:** Plan con 2 pasos independientes tarda menos que la suma de ambos (asyncio.gather). Plan con `depends_on` ejecuta en orden correcto.

---

## Fase 5 — Dynamic Tools + Candidate System ✅

**Objetivo:** Crear tools dinámicas persistidas localmente. Dos vías: usuario explícito (alta confianza) y agente automático (candidato, necesita promoción). Sistema de ciclo de vida: `candidate → validated → production`.

**Archivos afectados:**
- NEW `agent/tools_registry.py` — `DynamicToolRegistry` con lifecycle management
- NEW `agent/tools/generated/` — carpeta para código de tools generadas
- MOD `agent/executor.py` — pattern detection para auto-candidatos
- MOD `agent/agents/base_agent.py` — detectar intent "crea una herramienta/rutina" en prompt
- MOD `agent/main.py` — cargar generated tools al iniciar
- MOD `agent/context.py` — añadir referencia al registry

**Formato de tool generada** (`tools/generated/close_all_blinds.py`):
```python
# TOOL_METADATA — no modificar manualmente
TOOL_METADATA = {
    "name": "close_all_blinds",
    "description": "Cierra todas las persianas de la casa",
    "capabilities": ["home_automation", "blinds"],
    "origin": "user",           # "user" | "auto"
    "status": "validated",      # "candidate" | "validated" | "production"
    "confidence": 1.0,
    "version": "1.0",
    "usage_count": 0,
    "success_rate": None,
    "schema": {"type": "object", "properties": {}, "required": []},
}

async def close_all_blinds() -> str:
    """Cierra todas las persianas de la casa"""
    ...
```

**Reglas de promoción automática:**
```python
if tool.usage_count > 3 and tool.success_rate > 0.9:
    promote_to_production(tool)
```

**Vía usuario:** BaseAgent detecta "crea una herramienta/rutina para..." → llama a meta-tool interna `create_tool` → LLM genera código → status: `validated`.

**Vía agente:** Executor detecta 3+ llamadas al mismo tool con args similares en la sesión → crea candidato con status: `candidate`, confidence < 1.0 → no se ejecuta hasta promoción.

**Test mínimo:** Usuario pide "crea una rutina para cerrar la casa" → archivo aparece en `tools/generated/`. Al reiniciar, tool está disponible.

---

## Fase 6 — Metrics for Decisions + MCP Metadata ✅

**Objetivo:** El Executor consulta métricas antes de ejecutar un tool. Tools con success_rate bajo el threshold son evitadas. Tools MCP exponen version + success_rate.

**Archivos afectados:**
- MOD `agent/executor.py` — check `should_avoid_tool()` antes de ejecutar
- MOD `agent/tool_healing.py` — añadir `should_avoid_tool()` con threshold + min_calls
- MOD `agent/mcp_client.py` — enriquecer schema de tools MCP con metadata
- MOD `agent/agents/planner_agent.py` — considerar tool reliability en routing

**Lógica de avoidance:**
```python
MIN_CALLS = 5
SUCCESS_THRESHOLD = 0.8

def should_avoid_tool(metrics: dict) -> bool:
    calls = metrics.get("calls", 0)
    if calls < MIN_CALLS:
        return False  # insufficient data
    errors = metrics.get("errors", 0)
    return (calls - errors) / calls < SUCCESS_THRESHOLD
```

**Fallback cuando tool evitada:** Executor retorna `ToolResult(success=False, error_type="tool_degraded", content="Tool X is currently unreliable (success_rate < 80%). Cannot complete this step.")`. El agente lo reporta al usuario.

**MCP metadata (light):**
```python
# mcp_client.py — enriquecer tool dict con métricas actuales
tool["version"] = tool.get("version", "1.0")    # del servidor si lo provee
tool["success_rate"] = compute_from_metrics(tool_name)  # de memory
```

**Test mínimo:** Tool con 10 llamadas, 4 errores (60% success_rate) → `should_avoid_tool()` retorna True → Executor no la ejecuta → mensaje claro al usuario.

---

## Fase 7 — Data Collection (base para RL futuro) ✅

**Objetivo:** Detectar correcciones del usuario y guardarlas estructuradas en DB. No es RL, es la capa de recolección de datos que lo habilitará después.

**Archivos afectados:**
- MOD `agent/db/models.py` — añadir tabla `Correction` si no existe
- MOD `agent/db/recorder.py` — añadir `record_correction()`
- MOD `agent/agents/base_agent.py` — detectar correcciones en mensajes del usuario
- MOD `agent/event_worker.py` — pasar último tool call al contexto de corrección

**Patrones de detección:**
```python
CORRECTION_PATTERNS = [
    r"no era (el|la) (.+), era (el|la) (.+)",
    r"me refería a (.+)",
    r"quería decir (.+)",
    r"no (.+), (.+)",
]
```

**Estructura en DB:**
```json
{
    "type": "correction",
    "trace_id": "uuid",
    "tool": "set_blinds_state",
    "wrong_value": "salon",
    "correct_value": "dormitorio",
    "raw_message": "no era el salon, era el dormitorio",
    "timestamp": "..."
}
```

**Test mínimo:** Mensaje "no era el salon, era el dormitorio" después de llamar `set_blinds_state` → fila en tabla `Correction` con valores correctos.

---

## Resumen de archivos nuevos

| Archivo | Fase | Descripción |
|---------|------|-------------|
| `agent/executor.py` | 1 | Executor class (healing, retry, dispatch) |
| `agent/context.py` | 2 | AgentContext dataclass |
| `agent/tools_registry.py` | 5 | DynamicToolRegistry con lifecycle |
| `agent/tools/generated/` | 5 | Carpeta de tools generadas |

## Orden de implementación

```
Fase 1 → Fase 2 → Fase 3 → Fase 4 → Fase 5 → Fase 6 → Fase 7
  ↑          ↑        ↑        ↑
fundación  contexto  routing  paralelo
```

Cada fase se implementa y prueba antes de empezar la siguiente.
