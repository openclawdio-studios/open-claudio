# Modelo de Datos — Open-Claudio Observabilidad LLM

> Diseño de la base de datos PostgreSQL para persistir toda la actividad del sistema.
> Basado en el estándar **Trace/Span (OpenTelemetry)** — el mismo que usan Anthropic, OpenAI, Google.

---

## 1. Filosofía: ¿por qué Trace/Span?

Anthropic, OpenAI y Google convergen en el mismo modelo de observabilidad:

```
LangSmith (LangChain)  →  Traces + Runs
Langfuse (open-source) →  Traces + Observations
Phoenix (Arize)        →  Traces + Spans
Google Cloud Trace     →  Traces + Spans
OpenTelemetry (CNCF)   →  Traces + Spans  ← estándar abierto
```

El concepto es simple pero potente:

```
TRACE (1 request completo)
└── Span: planner              ← LLM descompone la tarea
    ├── Span: agent "home"     ← ReAct loop del sub-agente
    │   ├── Span: llm_call 1   ← LLM decide qué tool llamar
    │   ├── Span: tool_call    ← set_blinds_state(salon, off)
    │   └── Span: llm_call 2   ← LLM produce respuesta final
    └── Span: agent "knowledge"
        ├── Span: llm_call
        ├── Span: rag_retrieval ← búsqueda híbrida en ChromaDB
        └── Span: llm_call
```

Esto te da:
- **Latencia end-to-end** y **dónde se gasta el tiempo** (LLM vs tools vs RAG)
- **Coste de tokens** por request, por día, por agente
- **Reproducibilidad**: puedes replay cualquier conversación exacta
- **Debugging**: ves exactamente qué falló y en qué paso
- **Self-healing tracking**: cuántas veces se aplica cada fix

---

## 2. Diagrama Entidad-Relación

```
sessions ──< traces ──< spans ──< llm_calls
                  |         |
                  |         ├──< tool_calls
                  |         └──< rag_retrievals
                  |
                  └──< events

tool_fix_log          (standalone — correcciones aprendidas)
rag_documents         (catálogo del knowledge base)
feedback              (valoraciones humanas → traces)
```

---

## 3. Tablas y su propósito

### `sessions`
Agrupa múltiples turnos de un mismo usuario/canal. Permite ver el histórico completo de una conversación de Telegram, o todas las peticiones HTTP de una sesión.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | UUID | PK |
| `source` | VARCHAR(20) | `telegram` / `http` / `cli` / `mqtt` |
| `user_identifier` | TEXT | chat_id, IP hash, `cli` |
| `started_at` | TIMESTAMPTZ | primera actividad |
| `last_active_at` | TIMESTAMPTZ | última actividad |
| `message_count` | INTEGER | mensajes en la sesión |

---

### `traces` ← tabla central
Un trace = **un mensaje de usuario → una respuesta**. Es la unidad de negocio principal.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | UUID | PK |
| `session_id` | UUID FK | sesión a la que pertenece |
| `source` | VARCHAR(20) | canal de entrada |
| `user_input` | TEXT | texto literal del usuario |
| `final_output` | TEXT | respuesta final del agente |
| `status` | VARCHAR(20) | `running` / `success` / `error` / `timeout` / `max_steps` |
| `agent_plan` | JSONB | `[{agent, task}, ...]` del PlannerAgent |
| `tokens_prompt_total` | INTEGER | suma de todos los tokens de prompt del trace |
| `tokens_completion_total` | INTEGER | suma de todos los tokens de completion |
| `duration_ms` | INTEGER | tiempo total end-to-end |
| `created_at` | TIMESTAMPTZ | inicio |
| `completed_at` | TIMESTAMPTZ | fin |

---

### `spans` ← corazón de la observabilidad
Cada operación dentro de un trace es un span. Se anidan via `parent_span_id`.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | UUID | PK |
| `trace_id` | UUID FK | traza padre |
| `parent_span_id` | UUID FK | span padre (nesting) |
| `span_type` | VARCHAR(30) | `planner` / `agent_run` / `llm_call` / `tool_call` / `rag_retrieval` |
| `name` | TEXT | nombre específico: `home`, `set_blinds_state`, `rag_search` |
| `status` | VARCHAR(20) | `running` / `ok` / `error` |
| `started_at` | TIMESTAMPTZ | inicio del span |
| `ended_at` | TIMESTAMPTZ | fin del span |
| `duration_ms` | INTEGER | duración |
| `error_message` | TEXT | mensaje de error si falló |
| `metadata` | JSONB | datos adicionales flexibles |

**Jerarquía típica de spans para "cierra las persianas del salón":**
```
span: planner          (llm_call — descompone la tarea)
└── span: agent_run "home"
    ├── span: llm_call     (step 1 — LLM decide llamar set_blinds_state)
    ├── span: tool_call    (set_blinds_state — room=Ventana Salon, action=off)
    └── span: llm_call     (step 2 — LLM produce respuesta final)
```

---

### `llm_calls`
Detalle de cada llamada al LLM. Permite analizar tokens, latencias, y reproducir exactamente qué vio el modelo.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `span_id` | UUID FK | span al que pertenece |
| `model` | VARCHAR | `gpt-oss-20b` u otro |
| `messages` | JSONB | array completo de mensajes enviados |
| `response` | TEXT | respuesta del modelo |
| `tokens_prompt` | INTEGER | tokens de entrada |
| `tokens_completion` | INTEGER | tokens de salida |
| `temperature` | REAL | parámetro de sampling |
| `stop_reason` | VARCHAR(30) | `stop` / `tool_calls` / `max_tokens` / `error` |
| `duration_ms` | INTEGER | latencia de la llamada |

---

### `tool_calls`
Detalle de cada ejecución de tool. Incluye el **self-healing**: intentos, estrategia de reparación, si se aplicó un fix memorizado.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `span_id` | UUID FK | span al que pertenece |
| `tool_name` | VARCHAR | `set_blinds_state`, `rag_search`, etc. |
| `tool_source` | VARCHAR(30) | `local` / `mcp_domotics` / `mcp_fermax` / `mcp_rag` |
| `input_args` | JSONB | argumentos enviados |
| `output` | TEXT | resultado obtenido |
| `success` | BOOLEAN | éxito o fallo |
| `error_type` | VARCHAR | `connection_error` / `timeout` / `validation_error` / ... |
| `healing_strategy` | VARCHAR(30) | `retry` / `llm_fix` / `report` / `NULL` |
| `retries` | INTEGER | número de reintentos |
| `known_fix_applied` | BOOLEAN | se aplicó una corrección memorizada |
| `duration_ms` | INTEGER | latencia total (incluyendo reintentos) |

---

### `tool_fix_log`
Versión persistente (en DB) de los `tool_fixes` que ahora están en `memory.json`. Registra las correcciones de parámetros que el agente ha aprendido.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `agent_name` | VARCHAR | agente que aprendió el fix |
| `tool_name` | VARCHAR | tool afectada |
| `original_args` | JSONB | argumentos incorrectos que fallaron |
| `fixed_args` | JSONB | corrección que funcionó |
| `times_applied` | INTEGER | cuántas veces se ha reutilizado |
| `first_seen_at` | TIMESTAMPTZ | cuándo se aprendió |
| `last_applied_at` | TIMESTAMPTZ | última vez aplicado |

---

### `rag_retrievals`
Cada búsqueda en el knowledge base. Permite analizar qué se busca, con qué resultados, y detectar gaps (queries sin resultados = documentación que falta).

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `span_id` | UUID FK | span al que pertenece |
| `query` | TEXT | texto de búsqueda |
| `filter_type` | VARCHAR | filtro de doc_type si se usó |
| `k_requested` | INTEGER | cuántos resultados se pedían |
| `results_count` | INTEGER | cuántos se encontraron |
| `results` | JSONB | array con `{id, source, doc_type, relevance, text_snippet}` |
| `duration_ms` | INTEGER | latencia de retrieval |

---

### `rag_documents`
Catálogo authoritative del knowledge base. Es la fuente de verdad sobre qué está indexado en ChromaDB — reemplaza el estado implícito que ahora solo existe en ChromaDB.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `source` | VARCHAR UNIQUE | identificador único del documento |
| `doc_type` | VARCHAR | categoría: `manual` / `config` / `preference` / ... |
| `tags` | TEXT | etiquetas separadas por coma |
| `format` | VARCHAR | `pdf` / `markdown` / `text` |
| `file_path` | TEXT | ruta en `/docs` si viene de fichero |
| `chunk_count` | INTEGER | chunks indexados |
| `word_count_approx` | INTEGER | palabras aproximadas |
| `embedding_model` | VARCHAR | modelo usado para los embeddings |
| `ingested_at` | TIMESTAMPTZ | primera ingesta |
| `updated_at` | TIMESTAMPTZ | última actualización |
| `deleted_at` | TIMESTAMPTZ | soft delete — NULL = activo |

---

### `events`
Registro de todos los eventos entrantes (MQTT, Telegram, HTTP, CLI) con su payload completo y la ruta que hizo match.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `trace_id` | UUID FK | traza generada por este evento |
| `source` | VARCHAR | `mqtt` / `telegram` / `http` / `cli` |
| `event_type` | VARCHAR | `message` / `motion_detected` / `bell` / ... |
| `topic` | TEXT | MQTT topic o ruta lógica |
| `payload` | JSONB | datos del evento |
| `metadata` | JSONB | chat_id, QoS, etc. |
| `route_matched` | TEXT | nombre de la EventRoute que hizo match |
| `received_at` | TIMESTAMPTZ | cuándo llegó |
| `processed_at` | TIMESTAMPTZ | cuándo terminó de procesarse |
| `processing_ms` | INTEGER | tiempo total de procesamiento |

---

### `feedback`
Valoraciones humanas. Permite medir la calidad real de las respuestas y detectar degradaciones.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `trace_id` | UUID FK | respuesta valorada |
| `rating` | VARCHAR | `positive` / `negative` / `correction` |
| `comment` | TEXT | comentario libre |
| `corrected_output` | TEXT | respuesta correcta (si el usuario la proporcionó) |

---

## 4. Vistas analíticas incluidas

| Vista | Responde a |
|-------|-----------|
| `v_daily_token_usage` | ¿Cuántos tokens consumo por día? ¿Cuánto me costaría con OpenAI? |
| `v_tool_success_rates` | ¿Qué tools fallan más? ¿Cuánto se usa el self-healing? |
| `v_span_latency` | ¿Dónde se va el tiempo? ¿P95 de latencia por operación? |
| `v_rag_search_quality` | ¿Qué búsquedas no encuentran nada? ¿Qué documentación falta? |
| `v_knowledge_base_summary` | ¿Qué hay indexado y cuánto ocupa? |

---

## 5. Queries de ejemplo

```sql
-- Top 10 requests más lentos de la última semana
SELECT user_input, duration_ms, status, created_at
FROM traces
WHERE created_at > NOW() - INTERVAL '7 days'
ORDER BY duration_ms DESC NULLS LAST
LIMIT 10;

-- Tools que más fallan (candidatas a mejora)
SELECT tool_name, tool_source, total_calls, success_rate_pct, avg_retries
FROM v_tool_success_rates
WHERE total_calls > 5
ORDER BY success_rate_pct ASC;

-- Búsquedas RAG sin resultados (gaps de documentación)
SELECT query, COUNT(*) as times_asked
FROM v_rag_search_quality
WHERE result_quality = 'no_results'
GROUP BY query
ORDER BY times_asked DESC;

-- Coste estimado si usara gpt-4o ($5/1M prompt, $15/1M completion)
SELECT
    day,
    tokens_prompt,
    tokens_completion,
    ROUND((tokens_prompt / 1000000.0) * 5.0 +
          (tokens_completion / 1000000.0) * 15.0, 4) AS estimated_usd
FROM v_daily_token_usage
ORDER BY day DESC;

-- Conversación completa de una traza específica (replay)
SELECT
    s.span_type,
    s.name,
    s.duration_ms,
    lc.messages,
    lc.response,
    lc.tokens_prompt,
    lc.tokens_completion
FROM spans s
LEFT JOIN llm_calls lc ON lc.span_id = s.id
WHERE s.trace_id = '<uuid>'
ORDER BY s.started_at;

-- Fixes aprendidos más utilizados (top patrones de error recurrentes)
SELECT agent_name, tool_name, original_args, fixed_args, times_applied
FROM tool_fix_log
ORDER BY times_applied DESC
LIMIT 20;
```

---

## 6. Stack tecnológico recomendado

| Capa | Tecnología | Por qué |
|------|-----------|---------|
| **DB** | **PostgreSQL 16** | JSONB nativo, vistas materializadas, extensiones |
| **ORM / Driver** | **SQLAlchemy 2 + asyncpg** | async-first, compatible con el código asyncio actual |
| **Migraciones** | **Alembic** | estándar de la industria con SQLAlchemy |
| **Admin UI** | **Adminer** (Docker) | interfaz web ligera, zero-config |

### Añadir a docker-compose.yml

```yaml
postgres:
  image: postgres:16-alpine
  container_name: open-claudio-postgres
  environment:
    POSTGRES_DB: claudio
    POSTGRES_USER: claudio
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-claudio_dev}
  volumes:
    - postgres_data:/var/lib/postgresql/data
    - ./db/schema.sql:/docker-entrypoint-initdb.d/01_schema.sql:ro
  ports:
    - "5432:5432"
  networks:
    - claudio-net
  restart: unless-stopped

adminer:
  image: adminer:latest
  container_name: open-claudio-adminer
  ports:
    - "8090:8080"
  depends_on:
    - postgres
  networks:
    - claudio-net

volumes:
  postgres_data:
```

---

## 7. Roadmap de integración (por fases)

### Fase A — Infraestructura (sin tocar el agente)
- [ ] Añadir PostgreSQL + Adminer a docker-compose
- [ ] Crear `db/models.py` con SQLAlchemy models
- [ ] Crear `db/connection.py` con pool async

### Fase B — Instrumentación del agente
- [ ] `traces`: crear al recibir input, completar al responder
- [ ] `spans + llm_calls`: instrumentar `base_agent.py` y `planner_agent.py`
- [ ] `tool_calls`: instrumentar `_execute_tool` en `base_agent.py`
- [ ] `events`: instrumentar `event_worker.py`

### Fase C — RAG + Memory en DB
- [ ] `rag_retrievals`: instrumentar `rag_engine.search()`
- [ ] `rag_documents`: sincronizar con ChromaDB en `rag_engine.ingest/delete()`
- [ ] `tool_fix_log`: migrar `memory.json["tool_fixes"]` a DB

### Fase D — Analytics
- [ ] Dashboard con las vistas analíticas
- [ ] Alertas: tool_success_rate < 80%, latencia p95 > 5s
