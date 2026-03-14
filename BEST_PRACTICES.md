# Open-Claudio: Guía de Buenas Prácticas (Arquitectura ReAct + MCP)

Este documento establece las reglas fundamentales de arquitectura para **Open-Claudio**. Cualquier IA o desarrollador que trabaje en este proyecto **DEBE** respetar estos principios para mantener el sistema limpio, escalable y libre de acoplamiento.

## 1. Responsabilidad Única (SRP) en el Agente ReAct
El Agente (`agent/main.py`) es exclusivamente un **Motor de Razonamiento**.
- **PROHIBIDO** añadir lógica de dominio específico (ej: cómo conectarse a la API de Spotify, cómo calcular rutas de tráfico, cómo hablar con Z-Wave) directamente en el código del agente.
- **PERMITIDO**: El agente solo debe saber cómo leer el Sistema Operativo básico (ej: leer la hora, leer archivos locales esenciales como su memoria) y cómo descubrir herramientas externas dinámicamente vía MCP.

## 2. Model Context Protocol (MCP) como Frontera Estricta
Toda interacción con el mundo exterior (APIs, Domótica, Scraping, Bases de Datos) debe ocurrir a través de un servidor MCP.

### Reglas de los Servidores MCP:
1. **Un servidor por cada Dominio de Negocio**:
   - `mcp_domotics`: Solo para controlar cosas de la casa física (luces, persianas, sensores).
   - `mcp_media` (hipotético): Solo para controlar Spotify, Kodi, Plex, etc.
   - `mcp_system` (hipotético): Para ejecutar comandos shell, leer logs del sistema host, etc.
2. **Aislamiento en Docker**: Cada nuevo servidor MCP debe tener su propia carpeta (ej: `mcp_media/`), su propio `Dockerfile` y ser añadido como un servicio independiente en `docker-compose.yml`.
3. **Comunicación Estándar**: Los servidores MCP deben usar `FastMCP` (o el SDK oficial del lenguaje elegido) y comunicarse mediante SSE (Server-Sent Events) o Stdio. Nunca inventes clientes HTTP personalizados en el Agente.

## 3. Manejo de Herramientas y Prompts
- **Descripciones Claras**: Las herramientas exportadas (ej. con `@mcp.tool()`) deben tener docstrings de Python exhaustivos. El Agente usa estos docstrings literalmente para saber qué hace la herramienta.
  - *Mal*: `Abre la persiana`
  - *Bien*: `Controla una persiana individual en la casa. Recibe como argumento 'room' (el string con el nombre de la habitación) y 'action' (on, off, stop).`
- **Tolerancia a Fallos**: Si un servidor MCP cae, el script del cliente (`agent/mcp_client.py`) debe capturar el error para que el Agente ReAct no se cuelgue, sino que simplemente responda "No tengo acceso a las herramientas de domótica en este momento".

## 4. Gestión de Dependencias (Docker)
- **Bloqueos de Red**: Al construir los contenedores, preferir usar imágenes base locales o réplicas (como `alpine:latest` instalando python manualmente) si el entorno tiene problemas de red recurrentes con `docker.io`.
- **Variables de Entorno**: Ninguna API KEY, Token o URL privada local debe estar en el código fuente (`.py`). Todo debe inyectarse a través del bloque `environment:` en `docker-compose.yml` (y eventualmente un archivo `.env`). 
  *Ver ejemplo de `PERSIANAS_API_TOKEN` en `docker-compose.yml`.*

## 5. Migración de Skills Legacy (OpenClaw)
Al enfrentarse a una carpeta en `skills/` que contiene código heredado (ej: scripts `.js` sueltos):
1. Entiende qué hace el script invocándolo manualmente u observando su código.
2. Identifica a qué "Dominio" pertenece (Domótica, Media, OS, etc).
3. Escribe la versión Python pura equivalente dentro de `mcp_[dominio]/server.py`.
4. Borra el script original de Node.js de la carpeta `skills/`.

---
*Al seguir estas guías, Open-Claudio mantendrá su núcleo de IA ligero, mientras que el ecosistema a su alrededor (los servidores MCP) podrá crecer de forma infinita y en cualquier lenguaje de programación soportado por el estándar MCP.*
