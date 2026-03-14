# Guía: Cómo Añadir un Nuevo Servidor MCP a Open-Claudio

Open-Claudio usa una arquitectura puramente distribuida basada en **Modelo Context Protocol (MCP)**. Esto significa que **nunca añadas nuevos scripts de integraciones externas (skills) directamente al Agente ReAct**.

En su lugar, por cada "Dominio" (ej. Clima, Spotify, Portero Automático, Git), debes instanciar un servidor MCP pequeño, dockerizado y aislado.

Para integrar una nueva Skill/API, sigue estos **5 Pasos Fundamentales**:

## 1. Crear el Directorio del Servidor
Crea una carpeta nueva en la raíz del proyecto para tu servidor. El convenio de nombres es `mcp_[nombre_servicio]`. (Por ejemplo, si vamos a añadir control de Fermax: `mcp_fermax/`).

Dentro de esa carpeta, necesitas 3 archivos:

A. **`requirements.txt`**
Copia la base de cualquier otro servidor MCP (FastMCP) y añade tus librerías específicas (ej. `requests`):
```text
mcp[cli]
fastmcp
uvicorn
starlette
requests
```

B. **`Dockerfile`**
Usa la plantilla estándar de Alpine para evitar problemas con Docker Hub y aligerar la imagen:
```dockerfile
FROM alpine:latest
WORKDIR /app
RUN apk add --no-cache python3 py3-pip
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE <PUERTO_ÚNICO>  # Ej: 8001
CMD ["python", "-u", "server.py"]
```

C. **`server.py`**
La lógica de negocio utilizando FastMCP. ¡Recuerda escribir docstrings detallados para que el LLM sepa usar las herramientas!
```python
import os
import logging
from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
mcp = FastMCP("mi_nuevo_servicio")

# Lee las credenciales del entorno
MI_API_KEY = os.getenv("NUEVO_SERVICIO_API_KEY")

@mcp.tool()
def mi_nueva_herramienta(parametro: str) -> str:
    """Documentación vital para el Agente ReAct. Ejemplo: 
    Úsala para interactuar con X recibiendo Y.
    """
    return f"Resultado de interactuar con la API usando {parametro}"

if __name__ == "__main__":
    # IMPORTANTE: Cambia el puerto para que no colisione con otros MCPs (ej. 8001, 8002)
    mcp.run(transport="sse", host="0.0.0.0", port=8001)
```

## 2. Inyectar Credenciales
Nunca dejes contraseñas en el código fuente.
1. Abre `.env.example` y añade la definición de la nueva variable: `NUEVO_SERVICIO_API_KEY=tu_clave_aqui`
2. Si estás en local, cópiala a tu `.env` real: `NUEVO_SERVICIO_API_KEY=secreto_real123`

## 3. Registrar el Contenedor en `docker-compose.yml`
Declara tu nuevo servicio MCP en el bloque de `services:`:
```yaml
  mcp_fermax:
    build:
      context: ./mcp_fermax
    container_name: open-claudio-fermax
    ports:
      - "8001:8001"  # Puerto dedicado
    environment:
      - PYTHONUNBUFFERED=1
    env_file:
      - .env
    networks:
      - claudio-net
```

## 4. Enchufar el Servidor al Agente ReAct
Abre el archivo de configuración del Agente (generalmente `docker-compose.yml` o donde se definan las URLs de MCP).
Actualmente, el Agente (`agent/mcp_client.py` y `agent/main.py`) está diseñado para admitir un solo URL de manera directa a través de env var, pero en diseños Multi-MCP, debes configurar el Agente para iterar sobre una lista de endpoints.

*Para actualizar el Agente actual a Multi-MCP:*
Añade la URL separada por comas en `docker-compose.yml` bajo el servicio `agent`:
```yaml
      - MCP_SERVER_URLS=http://mcp_domotics:8000/sse,http://mcp_fermax:8001/sse
```
(Y asegúrate de que `agent/main.py` haga split de la variable y cree un cliente por cada URL instanciada).

## 5. Eliminar Rastros Legacy
Si estabas portando un script `bash` o `node` desde la carpeta `skills/`, elimínalo o exclúyelo vía `.gitignore` (ya hecho en `skills/.gitignore`). Esa antigua lógica de shell ahora vive aislada y limpiamente en sus contenedores MCP Dockerizados.

---
**¡Listo!** Con `docker-compose up -d --build`, el Agente se conectará a tu nuevo servicio, fusionará las nuevas `tools` en la cabeza del LLM Múltiple, y será mágicamente capaz de usar tu API.
