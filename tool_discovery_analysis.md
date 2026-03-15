# Análisis: Tool Auto-Discovery en Open-Claudio

## Veredicto: ✅ Ya lo estáis aplicando correctamente

La arquitectura actual de Open-Claudio **ya implementa los principios fundamentales** de tool auto-discovery que describe el documento. El agente **no tiene hardcodeadas** las tools de dominio — las descubre dinámicamente de los servidores MCP al arrancar.

## Lo que ya tenéis (y funciona bien)

| Principio del documento | Estado | Dónde |
|---|---|---|
| **Tool Registry dinámico** | ✅ | [mcp_client.py](file:///c:/ws/open-claudio/agent/mcp_client.py) — [MultiMCPClient](file:///c:/ws/open-claudio/agent/mcp_client.py#12-98) actúa como registry |
| **Discovery desde MCP servers** | ✅ | `session.list_tools()` en [connect()](file:///c:/ws/open-claudio/agent/mcp_client.py#L21-L54) |
| **Registro automático multi-servidor** | ✅ | Itera `MCP_SERVER_URLS` (env var con split por coma) |
| **Prompt dinámico de tools** | ✅ | [_build_openai_tools()](file:///c:/ws/open-claudio/agent/main.py#L45-L70) genera el schema en runtime |
| **Ejecución con routing automático** | ✅ | [call_tool()](file:///c:/ws/open-claudio/agent/mcp_client.py#L79-L97) busca qué servidor posee la tool |
| **Aislamiento por dominio** | ✅ | `mcp_domotics`, `mcp_fermax` — cada uno en su container |
| **Servidores configurables via env** | ✅ | `MCP_SERVER_URLS` en [docker-compose.yml](file:///c:/ws/open-claudio/docker-compose.yml) |
| **Guía para añadir nuevos servers** | ✅ | [ADDING_MCP.md](file:///c:/ws/open-claudio/ADDING_MCP.md) documenta el proceso |

## Flujo actual (ya es discovery)

```
Agent arranca
    │
    ▼
MultiMCPClient.connect()
    │
    ├─ MCP server: domotics → list_tools() → [set_blinds_state, set_all_blinds_state]
    ├─ MCP server: fermax   → list_tools() → [get_fermax_user_info, fermax_open_door, ...]
    │
    ▼
Tool Registry (self.connections[url]["tools"])
    │
    ▼
_build_openai_tools() → schema dinámico → LLM
```

Esto es exactamente el patrón del documento: **Discovery Manager → Tool Registry → LLM**.

## Mejoras opcionales para el futuro

Estas son mejoras **avanzadas** que no son necesarias ahora pero podrían ser relevantes si el sistema crece mucho:

### 1. Tool Retrieval con embeddings (cuando haya 50+ tools)
Ahora mismo tenéis ~6 tools. No necesitáis retrieval. Pero si llegarais a 50+, enviarlas todas al LLM saturará el prompt. En ese punto sería útil indexar las tools con embeddings y hacer top-K retrieval por query.

### 2. Tool namespaces
Si en el futuro hay colisiones de nombres entre servers (ej: dos servers con una tool `status`), se podría prefijar con el namespace del server: `domotics.set_blinds_state`, `fermax.get_device_info`.

### 3. Refresh periódico de tools
Actualmente las tools se descubren **una vez** al arrancar. Si un server MCP se reinicia y sus tools cambian en caliente, el agent no lo detectaría. Para un sistema de hogar esto es irrelevante, pero es una mejora potencial.

### 4. Health checks / reliability scores
Registrar qué tools fallan más para poder informar al LLM o hacer fallback automático.

> [!NOTE]
> Ninguna de estas mejoras es prioritaria con el tamaño actual del sistema. La arquitectura actual es correcta y sigue el espíritu del documento.
