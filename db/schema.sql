-- =============================================================================
-- Open-Claudio — PostgreSQL Schema
-- Modelo de observabilidad LLM basado en el estándar Trace/Span (OpenTelemetry)
-- =============================================================================

-- Extensiones
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()

-- =============================================================================
-- BLOQUE 1: SESIONES Y TRAZAS
-- Captura el ciclo de vida completo de cada interacción con el usuario
-- =============================================================================

-- Sesión: agrupa turnos de conversación del mismo usuario/canal
CREATE TABLE sessions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source           VARCHAR(20)  NOT NULL,  -- 'telegram' | 'http' | 'cli' | 'mqtt'
    user_identifier  TEXT,                   -- chat_id, IP hash, 'cli', MQTT client_id
    started_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_active_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    message_count    INTEGER      NOT NULL DEFAULT 0
);

-- Traza: un request completo de principio a fin (1 mensaje de usuario → 1 respuesta)
-- Equivale al "Trace" de OpenTelemetry / LangSmith / Langfuse
CREATE TABLE traces (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id               UUID REFERENCES sessions(id) ON DELETE SET NULL,
    source                   VARCHAR(20)  NOT NULL,
    user_input               TEXT         NOT NULL,
    final_output             TEXT,
    status                   VARCHAR(20)  NOT NULL DEFAULT 'running',
                             -- 'running' | 'success' | 'error' | 'timeout' | 'max_steps'
    agent_plan               JSONB,       -- [{agent, task}, ...] del PlannerAgent
    tokens_prompt_total      INTEGER      NOT NULL DEFAULT 0,
    tokens_completion_total  INTEGER      NOT NULL DEFAULT 0,
    duration_ms              INTEGER,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at             TIMESTAMPTZ
);

-- =============================================================================
-- BLOQUE 2: SPANS
-- Unidad mínima de observabilidad. Cada operación dentro de una traza es un span.
-- Sigue el modelo jerárquico de OpenTelemetry (parent_span_id para anidamiento).
-- =============================================================================

-- span_type posibles:
--   'planner'       → llamada LLM del PlannerAgent para descomponer la tarea
--   'agent_run'     → ejecución completa de un sub-agente (ReAct loop)
--   'llm_call'      → llamada individual al LLM dentro de un ReAct step
--   'tool_call'     → ejecución de una tool (local o MCP)
--   'rag_retrieval' → búsqueda híbrida en el knowledge base

CREATE TABLE spans (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id       UUID        NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    parent_span_id UUID        REFERENCES spans(id) ON DELETE SET NULL,
    span_type      VARCHAR(30) NOT NULL,
    name           TEXT        NOT NULL,  -- e.g. 'home', 'set_blinds_state', 'rag_search'
    status         VARCHAR(20) NOT NULL DEFAULT 'running',
                   -- 'running' | 'ok' | 'error'
    started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at       TIMESTAMPTZ,
    duration_ms    INTEGER,
    error_message  TEXT,
    metadata       JSONB       NOT NULL DEFAULT '{}'
);

-- =============================================================================
-- BLOQUE 3: DETALLE DE LLAMADAS LLM
-- Captura el contexto completo de cada inferencia: mensajes, tokens, parámetros
-- =============================================================================

CREATE TABLE llm_calls (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    span_id             UUID         NOT NULL REFERENCES spans(id) ON DELETE CASCADE,
    model               VARCHAR(100) NOT NULL,
    messages            JSONB        NOT NULL,   -- array completo de mensajes enviados
    response            TEXT,                    -- contenido de la respuesta
    tokens_prompt       INTEGER,
    tokens_completion   INTEGER,
    temperature         REAL,
    stop_reason         VARCHAR(30),
                        -- 'stop' | 'tool_calls' | 'max_tokens' | 'error'
    duration_ms         INTEGER,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- BLOQUE 4: DETALLE DE LLAMADAS A TOOLS
-- Incluye el self-healing: intentos, estrategia, correcciones aplicadas
-- =============================================================================

CREATE TABLE tool_calls (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    span_id             UUID         NOT NULL REFERENCES spans(id) ON DELETE CASCADE,
    tool_name           VARCHAR(100) NOT NULL,
    tool_source         VARCHAR(30)  NOT NULL,
                        -- 'local' | 'mcp_domotics' | 'mcp_fermax' | 'mcp_rag'
    input_args          JSONB        NOT NULL DEFAULT '{}',
    output              TEXT,
    success             BOOLEAN      NOT NULL DEFAULT FALSE,
    error_type          VARCHAR(50),
                        -- 'connection_error' | 'timeout' | 'validation_error' |
                        -- 'permission_error' | 'tool_not_found' | 'unknown_error'
    healing_strategy    VARCHAR(30),
                        -- NULL | 'retry' | 'llm_fix' | 'report' | 'retry_then_report'
    retries             INTEGER      NOT NULL DEFAULT 0,
    known_fix_applied   BOOLEAN      NOT NULL DEFAULT FALSE,
    duration_ms         INTEGER,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- BLOQUE 5: SELF-HEALING — CORRECCIONES APRENDIDAS
-- Persistencia de las correcciones de parámetros que el agente aprende con el tiempo
-- =============================================================================

CREATE TABLE tool_fix_log (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name       VARCHAR(100) NOT NULL,
    tool_name        VARCHAR(100) NOT NULL,
    original_args    JSONB        NOT NULL,  -- argumentos incorrectos que fallaron
    fixed_args       JSONB        NOT NULL,  -- corrección aplicada con éxito
    times_applied    INTEGER      NOT NULL DEFAULT 1,
    first_seen_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_applied_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (agent_name, tool_name, original_args)
);

-- =============================================================================
-- BLOQUE 6: RAG — BÚSQUEDAS Y CATÁLOGO DE DOCUMENTOS
-- =============================================================================

-- Log de cada búsqueda en el knowledge base
CREATE TABLE rag_retrievals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    span_id         UUID        NOT NULL REFERENCES spans(id) ON DELETE CASCADE,
    query           TEXT        NOT NULL,
    filter_type     VARCHAR(50),                 -- doc_type filter si se usó
    k_requested     INTEGER     NOT NULL DEFAULT 5,
    results_count   INTEGER     NOT NULL DEFAULT 0,
    -- Resultados: [{id, source, doc_type, relevance, text_snippet}]
    results         JSONB       NOT NULL DEFAULT '[]',
    duration_ms     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Catálogo de documentos indexados (source of truth sobre qué hay en ChromaDB)
CREATE TABLE rag_documents (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source           VARCHAR(255) NOT NULL UNIQUE,  -- identificador único del doc
    doc_type         VARCHAR(50)  NOT NULL,
                     -- 'manual' | 'config' | 'log' | 'preference' |
                     -- 'conversation' | 'how_to' | 'other'
    tags             TEXT,                           -- etiquetas separadas por coma
    format           VARCHAR(20),                    -- 'pdf' | 'markdown' | 'text'
    file_path        TEXT,                           -- ruta en /docs si aplica
    chunk_count      INTEGER      NOT NULL DEFAULT 0,
    word_count_approx INTEGER,
    embedding_model  VARCHAR(100) NOT NULL DEFAULT 'nomic-ai/nomic-embed-text-v1.5',
    ingested_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at       TIMESTAMPTZ  -- soft delete: NULL = activo
);

-- =============================================================================
-- BLOQUE 7: EVENTOS ENTRANTES
-- Registro de todos los eventos recibidos de fuentes externas
-- =============================================================================

CREATE TABLE events (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id       UUID        REFERENCES traces(id) ON DELETE SET NULL,
    source         VARCHAR(20) NOT NULL,   -- 'mqtt' | 'telegram' | 'http' | 'cli'
    event_type     VARCHAR(100),           -- e.g. 'message', 'motion_detected', 'bell'
    topic          TEXT,                   -- MQTT topic o ruta lógica
    payload        JSONB       NOT NULL DEFAULT '{}',
    metadata       JSONB       NOT NULL DEFAULT '{}',
    route_matched  TEXT,                   -- nombre de la ruta que hizo match
    received_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at   TIMESTAMPTZ,
    processing_ms  INTEGER
);

-- =============================================================================
-- BLOQUE 8: FEEDBACK HUMANO
-- Valoraciones del usuario sobre las respuestas del agente
-- =============================================================================

CREATE TABLE feedback (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id          UUID        NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    rating            VARCHAR(20) NOT NULL,
                      -- 'positive' | 'negative' | 'correction'
    comment           TEXT,
    corrected_output  TEXT,        -- si el usuario corrigió la respuesta
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- ÍNDICES — optimizados para las queries de observabilidad más frecuentes
-- =============================================================================

-- Trazas: filtrar por fecha, estado, origen
CREATE INDEX idx_traces_created_at    ON traces (created_at DESC);
CREATE INDEX idx_traces_status        ON traces (status);
CREATE INDEX idx_traces_source        ON traces (source);
CREATE INDEX idx_traces_session       ON traces (session_id);

-- Spans: navegar jerarquía
CREATE INDEX idx_spans_trace_id       ON spans (trace_id);
CREATE INDEX idx_spans_parent_id      ON spans (parent_span_id);
CREATE INDEX idx_spans_type           ON spans (span_type);
CREATE INDEX idx_spans_started_at     ON spans (started_at DESC);

-- LLM Calls: análisis de tokens y modelos
CREATE INDEX idx_llm_calls_span       ON llm_calls (span_id);
CREATE INDEX idx_llm_calls_model      ON llm_calls (model);
CREATE INDEX idx_llm_calls_created_at ON llm_calls (created_at DESC);

-- Tool Calls: análisis de éxito/error por tool
CREATE INDEX idx_tool_calls_span      ON tool_calls (span_id);
CREATE INDEX idx_tool_calls_name      ON tool_calls (tool_name);
CREATE INDEX idx_tool_calls_success   ON tool_calls (success);
CREATE INDEX idx_tool_calls_source    ON tool_calls (tool_source);

-- RAG: queries frecuentes sobre documentos
CREATE INDEX idx_rag_docs_doc_type    ON rag_documents (doc_type);
CREATE INDEX idx_rag_docs_deleted     ON rag_documents (deleted_at) WHERE deleted_at IS NULL;
CREATE INDEX idx_rag_ret_created_at   ON rag_retrievals (created_at DESC);

-- Eventos: filtrar por fuente y fecha
CREATE INDEX idx_events_source        ON events (source);
CREATE INDEX idx_events_received_at   ON events (received_at DESC);
CREATE INDEX idx_events_trace         ON events (trace_id);

-- =============================================================================
-- VISTAS ANALÍTICAS
-- =============================================================================

-- Coste de tokens por día y modelo
CREATE VIEW v_daily_token_usage AS
SELECT
    date_trunc('day', lc.created_at)   AS day,
    lc.model,
    COUNT(*)                            AS llm_calls,
    SUM(lc.tokens_prompt)               AS tokens_prompt,
    SUM(lc.tokens_completion)           AS tokens_completion,
    SUM(lc.tokens_prompt + lc.tokens_completion) AS tokens_total,
    AVG(lc.duration_ms)                 AS avg_latency_ms
FROM llm_calls lc
GROUP BY 1, 2
ORDER BY 1 DESC, tokens_total DESC;

-- Tasa de éxito por tool
CREATE VIEW v_tool_success_rates AS
SELECT
    tc.tool_name,
    tc.tool_source,
    COUNT(*)                                               AS total_calls,
    SUM(CASE WHEN tc.success THEN 1 ELSE 0 END)            AS successful,
    ROUND(
        100.0 * SUM(CASE WHEN tc.success THEN 1 ELSE 0 END) / COUNT(*), 2
    )                                                      AS success_rate_pct,
    AVG(tc.retries)                                        AS avg_retries,
    AVG(tc.duration_ms)                                    AS avg_duration_ms,
    SUM(CASE WHEN tc.healing_strategy IS NOT NULL THEN 1 ELSE 0 END) AS healed_calls
FROM tool_calls tc
GROUP BY 1, 2
ORDER BY total_calls DESC;

-- Latencia por tipo de span (dónde se gasta el tiempo)
CREATE VIEW v_span_latency AS
SELECT
    s.span_type,
    s.name,
    COUNT(*)              AS executions,
    AVG(s.duration_ms)    AS avg_ms,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY s.duration_ms) AS p50_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY s.duration_ms) AS p95_ms,
    MAX(s.duration_ms)    AS max_ms,
    SUM(CASE WHEN s.status = 'error' THEN 1 ELSE 0 END) AS errors
FROM spans s
WHERE s.duration_ms IS NOT NULL
GROUP BY 1, 2
ORDER BY avg_ms DESC;

-- Calidad del RAG: queries con pocos resultados o sin resultados
CREATE VIEW v_rag_search_quality AS
SELECT
    rr.query,
    rr.filter_type,
    rr.k_requested,
    rr.results_count,
    rr.duration_ms,
    rr.created_at,
    CASE
        WHEN rr.results_count = 0               THEN 'no_results'
        WHEN rr.results_count < rr.k_requested  THEN 'partial'
        ELSE                                         'full'
    END AS result_quality
FROM rag_retrievals rr
ORDER BY rr.created_at DESC;

-- Resumen del knowledge base (documentos activos)
CREATE VIEW v_knowledge_base_summary AS
SELECT
    doc_type,
    format,
    COUNT(*)            AS documents,
    SUM(chunk_count)    AS total_chunks,
    SUM(word_count_approx) AS total_words_approx,
    MIN(ingested_at)    AS oldest_ingestion,
    MAX(updated_at)     AS latest_update
FROM rag_documents
WHERE deleted_at IS NULL
GROUP BY 1, 2
ORDER BY total_chunks DESC;
