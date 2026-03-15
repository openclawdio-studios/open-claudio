# Guía de Ingesta RAG — Mejores Prácticas

> Referencia para indexar documentos en el knowledge base de Open-Claudio.
> Aplica a: `rag_ingest`, `rag_ingest_file`.

---

## 1. Principio fundamental: calidad > cantidad

> "Garbage in, garbage out."
> Un retrieval con 50 documentos bien preparados supera a uno con 500 mal procesados.

El embedding model (`nomic-embed-text-v1.5`) convierte texto en vectores de 768 dimensiones.
**Lo que el modelo no puede ver, no puede recuperar.** La preparación del documento es el 60% del trabajo.

---

## 2. El modelo: nomic-embed-text-v1.5

Este modelo requiere **prefijos de tarea** — es su característica más importante:

| Contexto | Prefijo | Cuándo |
|---------|---------|--------|
| Indexar un chunk | `search_document: <texto>` | Automático en `rag_ingest` |
| Hacer una búsqueda | `search_query: <texto>` | Automático en `rag_search` |

**No añadas estos prefijos manualmente** — el sistema los gestiona internamente.
Si algún día cambias el modelo a uno que no los necesite, solo cambia `rag_engine.py`.

---

## 3. Formatos soportados

### Plain text (`.txt`)
El formato más simple. Se normaliza el whitespace.

```
# Ideal para:
- Logs del sistema
- Notas de texto plano
- Exports de configuración
- Preferencias del usuario escritas a mano
```

**Antes de ingestar:** elimina timestamps repetitivos en logs, elimina líneas completamente vacías en exceso.

---

### Markdown (`.md`, `.markdown`)
El parser elimina la sintaxis de formato pero **preserva todo el texto**, incluyendo el de los headers y listas.

```
# Ideal para:
- READMEs y documentación técnica
- Wikis personales / Obsidian vaults
- How-to guides
- Notas de Notion exportadas
```

**Antes de ingestar:**
- Asegúrate de que los headers (`# H1`, `## H2`) describen bien la sección — son el anchor semántico más valioso
- Evita imágenes sin texto alternativo (el parser las elimina completamente)
- Los bloques de código se conservan — si no son relevantes para la búsqueda, elimínalos antes

**Ejemplo de buen Markdown para RAG:**
```markdown
## Configuración de persianas Z-Wave

Las persianas Z-Wave del salón aceptan tres comandos: on (subir), off (bajar), stop (detener).
El dispositivo del salón tiene dos motores: Ventana Salon y Puerta Salon.

### Cómo subir solo la ventana del salón
Usar el comando set_blinds_state con room="Ventana Salon" y action="on".
```

**Ejemplo de Markdown malo para RAG:**
```markdown
## Config

Ver imagen adjunta. [Foto](./foto.jpg)
```

---

### PDF (`.pdf`)
El parser usa **PyMuPDF** (la librería más robusta disponible en Python). Extrae texto página a página con marcadores `[Page N]`.

```
# Ideal para:
- Manuales de dispositivos (Z-Wave, Fermax, etc.)
- Datasheets técnicos
- Documentos de configuración
```

**Limitaciones importantes:**

| Tipo de PDF | Resultado |
|------------|---------|
| PDF con texto nativo (digital) | ✅ Perfecto |
| PDF escaneado SIN OCR | ❌ Vacío — no hay capa de texto |
| PDF con texto en imágenes | ❌ Vacío |
| PDF multi-columna | ⚠️ Texto mezclado — requiere revisión |
| PDF protegido con contraseña | ❌ Error |

**Si tienes un PDF escaneado:** usa una herramienta de OCR externa primero:
```bash
# Opción 1: ocrmypdf (añade capa de texto al PDF)
ocrmypdf -l spa input.pdf output_with_text.pdf

# Opción 2: tesseract (exporta a .txt)
tesseract input.pdf output -l spa
```

**Antes de ingestar un PDF:**
1. Ábrelo y confirma que tiene texto seleccionable (no es escaneado)
2. Si tiene encabezados/pies de página repetitivos en cada hoja, considera limpiarlos
3. PDFs muy grandes (>100 páginas): considera dividirlos por secciones temáticas y usar `source` distinto para cada sección

---

## 4. Estrategia de chunking

El sistema usa **chunking por párrafos** con ventana deslizante de 50 palabras de overlap.

### Parámetros por defecto

| Parámetro | Valor | Qué controla |
|-----------|-------|-------------|
| `chunk_size` | 400 palabras | Tamaño máximo del chunk |
| `overlap` | 50 palabras | Palabras compartidas entre chunks consecutivos |

### Cuándo cambiar los defaults

```python
# Para documentos con párrafos muy cortos (logs, configs):
# chunk_size más pequeño evita mezclar contextos
chunk_size=200, overlap=30

# Para documentos narrativos largos (manuales completos):
# chunk_size más grande preserva más contexto
chunk_size=600, overlap=80
```

> Los defaults son los actualmente hardcodeados en `ingestion.py`.
> Si necesitas cambiarlos por tipo de documento, se puede exponer como parámetro en el futuro.

### Regla de oro del chunk size

- **Muy pequeño** (< 100 palabras): el chunk pierde contexto, el retrieval encuentra fragmentos sin sentido
- **Muy grande** (> 800 palabras): un chunk habla de demasiadas cosas, la similitud semántica se diluye
- **Sweet spot**: 300-500 palabras para documentación técnica

---

## 5. Diseño de metadatos

Los metadatos son la segunda palanca más importante después de la calidad del texto.

### Campos disponibles

| Campo | Tipo | Descripción | Ejemplo |
|-------|------|-------------|---------|
| `source` | string | Identificador único del documento | `"fermax_manual_v2"` |
| `doc_type` | string | Categoría para filtrado | `"manual"` |
| `tags` | string | Labels separados por comas | `"fermax,intercom,door"` |

### doc_type: valores recomendados

```
manual        → documentación de dispositivo / API
config        → ficheros de configuración del sistema
preference    → preferencias del usuario
log           → logs del sistema
conversation  → historial de conversaciones importante
how_to        → guías de procedimiento paso a paso
other         → cualquier otra cosa
```

**Por qué importa:** `rag_search(query, filter_type="manual")` solo busca en manuales.
El Planner puede indicar al agente knowledge que filtre por tipo según el contexto de la pregunta.

### Convención de naming para `source`

```
# Patrón recomendado: <dispositivo_o_dominio>_<tipo>_<version_o_fecha>
fermax_intercom_manual_v1
zwave_blinds_manual_2024
nas_synology_setup
user_preferences
home_layout_description
agent_tools_reference
```

**Regla:** el `source` debe ser suficientemente descriptivo para que al leerlo en `rag_list_sources` sepas qué contiene.

---

## 6. Workflow de ingesta recomendado

### Paso 1 — Preparar el fichero
```
docs/
├── manuals/
│   ├── fermax_manual.pdf
│   └── zwave_blinds_manual.pdf
├── configs/
│   └── home_layout.md
└── preferences/
    └── user_prefs.txt
```

### Paso 2 — Ingestar via agente
```
"Ingesta el fichero /docs/manuals/fermax_manual.pdf como doc_type=manual con tags=fermax,intercom,door"
```

O directamente:
```
"Usa rag_ingest_file con file_path=/docs/manuals/fermax_manual.pdf, doc_type=manual, tags=fermax,intercom"
```

### Paso 3 — Verificar la ingesta
```
"Lista los documentos del knowledge base"
```
→ `rag_list_sources()` muestra fuentes y número de chunks.

### Paso 4 — Probar el retrieval
```
"Busca en el knowledge base cómo abrir la puerta del intercom"
```
→ Verifica que el resultado contiene información relevante del manual.

---

## 7. Cuándo re-ingestar

El sistema tiene comportamiento **upsert**: re-ingestar el mismo `source` reemplaza los chunks anteriores.

```
# Re-ingestar cuando:
- El documento fuente ha cambiado (nueva versión del manual)
- El chunking era incorrecto (texto mal dividido)
- Añadiste contexto importante al documento
```

---

## 8. Fase 3 — Contextual RAG (próximamente)

Esta técnica de Anthropic (sept. 2024) mejora el retrieval un **49%** en benchmarks.
Antes de hacer embedding de cada chunk, el LLM genera una frase de contexto:

```
# Chunk original:
"La persiana del salón acepta: on, off, stop"

# Chunk con contexto (generado por LLM durante ingesta):
"[Contexto: Manual Z-Wave, sección comandos del salón]
La persiana del salón acepta: on, off, stop"
```

El embedding del chunk contextualizado es mucho más preciso porque "entiende" a qué documento pertenece.
**Coste:** 1 llamada LLM por chunk, solo durante ingesta (no afecta a la velocidad de búsqueda).

Implementación prevista en Fase 3 del roadmap.

---

## 9. Errores comunes

| Error | Causa | Solución |
|-------|-------|---------|
| Retrieval devuelve chunks irrelevantes | Documento mal preparado / demasiado ruido | Limpiar el doc antes de ingestar |
| "Empty content — nothing ingested" | El fichero está vacío o es un PDF escaneado | Verificar que el PDF tiene texto, usar OCR si es escaneado |
| "Access denied: files must be inside /docs" | Ruta fuera de `/docs` | Mover el fichero a `./docs/` en el host |
| Chunks muy cortos en el resultado | chunk_size demasiado pequeño | Aumentar a 400+ para docs técnicos |
| El agente no encuentra info que sí existe | Query demasiado específica o en diferente idioma | Reformular la query, o probar en el idioma del doc |

---

## 10. Checklist rápida antes de ingestar

- [ ] El documento tiene texto real (no es escaneado / imagen)
- [ ] Encoding UTF-8 (o Latin-1 para documentos españoles antiguos)
- [ ] `source` es único y descriptivo
- [ ] `doc_type` elegido correctamente para poder filtrar después
- [ ] `tags` incluyen el dispositivo / dominio relevante
- [ ] Para PDFs: verificado que el texto es seleccionable en el lector PDF
- [ ] Para Markdown: headers descriptivos en todas las secciones
