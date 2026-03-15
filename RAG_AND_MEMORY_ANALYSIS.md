# RAG & Memory Analysis — Open-Claudio

> Análisis de estado actual y plan de mejora para los componentes de RAG y MEMORY.
> Fecha: 2026-03-15

---

## Arquitectura de referencia

Un agente potente combina 4 sistemas:

```
              AGENTE
                │
   ┌────────────┼────────────┐
   │            │            │
MEMORY        RAG         TOOLS
   │            │            │
experiencia  conocimiento   acciones
```

Más un **planner** que decide qué hacer.

---

## 1. MEMORY — Diagnóstico

### Lo bueno ✓
- **Namespacing por agente** (`memory["home"]`, etc.) — patrón correcto
- **Self-healing con `tool_fixes`** — aprende de errores de parámetros
- **Métricas por tool** — buena observabilidad básica

### Problemas vs. mejores prácticas

| Gap | Detalle | Impacto |
|-----|---------|---------|
| **Sin memoria entre sesiones** | El `messages` list en `base_agent.run()` vive solo dentro de esa llamada | El agente no recuerda conversaciones pasadas |
| **Dump completo al system prompt** | `json.dumps(llm_memory)` → tokens desperdiciados y sin relevancia | Escala fatal cuando crece |
| **Sin hechos estructurados** | No hay `{"type": "user_preference", "key": "nas_ip", "value": "192.168.1.20"}` | No puede razonar sobre su propio conocimiento |
| **Memoria no es una tool** | Los agentes no pueden `memory_save()` ni `memory_search()` — la memoria es pasiva | Agentes no pueden aprender activamente |
| **Bug de duplicación** | `tool_metrics` aparece tanto en la raíz como en `memory["home"]` | Datos inconsistentes |
| **Sin TTL ni scoring** | Datos viejos nunca expiran | Contamina el contexto a largo plazo |

### Cómo debería funcionar (Anthropic/OpenAI/Google)

Los tres enfoques coinciden: **la memoria es una herramienta, no una inyección pasiva**.

```python
# Patrón correcto

# Short-term: ya funciona — el messages[] dentro de run() es la conversación activa
# Long-term: los agentes escriben explícitamente hechos importantes

memory_save(key="user_prefers_backup_at_night", value=True, type="preference")
memory_search(query="backup preferences")   # retrieval semántico, no dump completo
```

**Mejoras concretas (Fase 1):**
1. Estructura los entries: `{type, key, value, timestamp, ttl, source_agent}`
2. Añade `memory_save` y `memory_search` como local tools en `tools.py`
3. Los agentes escriben en memoria durante su ReAct loop
4. El system prompt solo inyecta los K hechos más relevantes, no todo el JSON

---

## 2. RAG — Diseño completo

### Filosofía de arquitectura

Siguiendo la regla de diseño del proyecto: **el agente es un motor de razonamiento puro**. El RAG va como un nuevo contenedor MCP.

```
mcp_rag/
├── server.py       # FastMCP server (igual que mcp_domotics)
├── rag_engine.py   # lógica de retrieval + hybrid search
├── ingestion.py    # chunking + contextual embedding
└── data/           # ChromaDB persistente (volume)
```

### Stack recomendado (home server, sin API externa)

| Componente | Tecnología | Por qué |
|-----------|-----------|---------|
| **Embedding** | `sentence-transformers` (`all-MiniLM-L6-v2`) | Local, rápido, sin API key |
| **Vector DB** | **ChromaDB** (embedded mode) | Un solo proceso, persistencia en fichero, zero-config |
| **Keyword search** | `rank_bm25` | Complementa semántica con keywords exactas |
| **Merge strategy** | Reciprocal Rank Fusion (RRF) | Estándar en hybrid search |
| **Chunking** | Recursive text splitter con overlap | Preserva contexto entre chunks |

### Técnica avanzada: Contextual RAG (Anthropic, sept. 2024)

Antes de hacer embedding de cada chunk, el LLM genera una frase de contexto:

```
# Sin Contextual RAG (naive):
chunk = "La persiana del salón acepta: open, close, half"

# Con Contextual RAG:
contextualized_chunk = """
[Contexto: Este fragmento es del manual de persianas Z-Wave, sección comandos del salón]
La persiana del salón acepta: open, close, half
"""
```

Resultado: **49% menos fallos de retrieval** (benchmarks Anthropic). Coste: una llamada LLM por chunk durante ingesta, no durante retrieval.

### Herramientas MCP que expondrá `mcp_rag`

```python
rag_search(query: str, k: int = 5, filter_type: str = None) -> list[dict]
rag_ingest(content: str, source: str, doc_type: str, tags: list[str] = []) -> dict
rag_list_sources() -> list[dict]
```

### Integración en el flujo del agente

**Agente `knowledge` dedicado** (recomendado — sigue el principio SOA del proyecto):

```python
# PlannerAgent descompone así:
User: "¿Cómo configuro la persiana del dormitorio?"
Plan: [
  {"agent": "knowledge", "task": "Busca documentación sobre configuración de persianas Z-Wave"},
  {"agent": "home",      "task": "Aplica la configuración encontrada"}
]
```

### Qué documentos indexar

1. Manuales de dispositivos (persianas Z-Wave, Fermax intercom)
2. Logs del sistema (para diagnóstico de fallos)
3. Preferencias del usuario (formato estructurado)
4. Documentación de los MCP tools (para que el agente aprenda sus propias capacidades)
5. Historial de conversaciones importantes

---

## 3. Arquitectura objetivo

```
User
 │
 ▼
PlannerAgent
 │
 ├── memory_search()   ← long-term structured facts
 │
 ├── rag_search()      ← mcp_rag (ChromaDB + hybrid search)
 │
 ├── home / server / intercom / utility / knowledge agents
 │        │
 │        └── memory_save()  ← agentes escriben hechos activamente
 │
 └── MCP tools (mcp_domotics, mcp_rag, mcp_fermax, ...)
```

---

## 4. Plan de implementación por fases

### Fase 1 — Fix MEMORY (bajo esfuerzo, alto impacto)
- [ ] Añadir `memory_save(key, value, type)` y `memory_search(query)` a `tools.py`
- [ ] Estructurar entries en `memory.json` con metadatos
- [ ] Cambiar system prompt de "dump todo" a "top-5 facts relevantes"
- [ ] Eliminar duplicación de `tool_metrics` raíz vs agentes

### Fase 2 — mcp_rag básico (nuevo contenedor) ← COMENZANDO AQUÍ
- [ ] Crear `mcp_rag/` con FastMCP + ChromaDB + sentence-transformers
- [ ] Implementar `rag_search` y `rag_ingest` con hybrid search (vector + BM25)
- [ ] Añadir a `docker-compose.yml`
- [ ] Crear agente `knowledge` en `agents/knowledge_agent.py`
- [ ] Registrar en PlannerAgent

### Fase 3 — Contextual RAG (calidad)
- [ ] Pipeline de ingesta que genera contexto LLM por chunk antes de embedding
- [ ] Script de ingesta inicial de documentos
- [ ] Auto-ingesta de logs y conversaciones relevantes
