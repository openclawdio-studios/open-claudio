from fastmcp import FastMCP
import uvicorn
import logging
import os
import requests
import unicodedata
from typing import Literal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_domotics")

API_URL = os.getenv("PERSIANAS_API_URL", "https://northr3nd.duckdns.org")
API_TOKEN = os.getenv("PERSIANAS_API_TOKEN", None)

# Each house blind has TWO motors: one for the window part (Ventana) and one for the door part (Puerta).
# This is the exhaustive mapping of human-readable names to Z-Wave device IDs.
DEVICE_MAPPING = {
    'Ventana Hab. Principal': 'ZWayVDev_zway_3-0-38',
    'Puerta Hab. Principal':  'ZWayVDev_zway_8-0-38',
    'Ventana Salon':          'ZWayVDev_zway_4-0-38',
    'Puerta Salon':           'ZWayVDev_zway_2-0-38',
    'Ventana Ordenadores':    'ZWayVDev_zway_7-0-38',
    'Ventana Hab. Jaume/Edu': 'ZWayVDev_zway_9-0-38',
}

# Valid Z-Wave multilevel switch commands
VALID_ACTIONS = ['on', 'off', 'stop']

def _normalize(s: str) -> str:
    """Remove accents and lowercase for fuzzy matching."""
    return unicodedata.normalize('NFD', s.lower()).encode('ascii', 'ignore').decode('utf-8')

def _resolve_device_id(device: str) -> str | None:
    """Resolve a human-readable device name to its Z-Wave ID, with fuzzy fallback."""
    # Exact match
    if device in DEVICE_MAPPING:
        return DEVICE_MAPPING[device]
    
    # Normalized exact match (handles accents)
    normalized_device = _normalize(device)
    for k, v in DEVICE_MAPPING.items():
        if _normalize(k) == normalized_device:
            return v
    
    # Fuzzy substring match: e.g. "salon" matches "Ventana Salon"
    for k, v in DEVICE_MAPPING.items():
        if normalized_device in _normalize(k):
            logger.info(f"Fuzzy matched '{device}' to '{k}'")
            return v
            
    if device.startswith('ZWayVDev_'):
        return device
    return None

def _send_command(device_id: str, action: str) -> bool:
    """Send a Z-Wave command to the device via the home automation API (GET request)."""
    base_url = API_URL.rstrip('/')
    url = f"{base_url}/api/devices/{device_id}/command/{action}"
    headers = {}
    if API_TOKEN:
        headers['Authorization'] = f"Bearer {API_TOKEN}"
        
    try:
        logger.info(f"Sending command: GET {url}")
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        return True
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP Error calling {url}: {e.response.status_code} - {e.response.text}")
        return False
    except Exception as e:
        logger.error(f"Error calling {url}: {e}")
        return False

# ----- FastMCP Server -----
mcp = FastMCP("domotics")

# We use Literal types so that the JSON Schema produced by FastMCP explicitly
# enumerates the allowed values. This is CRITICAL for LLMs to know what to send.

RoomType = Literal[
    'Ventana Salon',
    'Puerta Salon',
    'Ventana Hab. Principal',
    'Puerta Hab. Principal',
    'Ventana Ordenadores',
    'Ventana Hab. Jaume/Edu',
]

ActionType = Literal['on', 'off', 'stop']

@mcp.tool()
def set_blinds_state(room: RoomType, action: ActionType) -> str:
    """Sube, baja o detiene la persiana de una habitación concreta de la casa.

    IMPORTANTE - Significado de cada acción:
      - 'on'   = SUBIR la persiana (abrir, dejar pasar la luz)
      - 'off'  = BAJAR la persiana (cerrar, bloquear la luz)
      - 'stop' = DETENER la persiana en su posición actual

    Dispositivos disponibles por habitación:
      - 'Ventana Salon'           → persiana de la ventana del salón
      - 'Puerta Salon'            → persiana de la puerta del salón
      - 'Ventana Hab. Principal'  → persiana de la ventana del dormitorio principal
      - 'Puerta Hab. Principal'   → persiana de la puerta del dormitorio principal
      - 'Ventana Ordenadores'     → persiana de la habitación de ordenadores / despacho
      - 'Ventana Hab. Jaume/Edu'  → persiana de la habitación de Jaume y Edu

    Args:
        room: Nombre exacto de la persiana a controlar (ver lista arriba).
        action: Comando a enviar: 'on' (subir), 'off' (bajar), 'stop' (detener).
    """
    logger.info(f"Command received: set_blinds_state room='{room}' action='{action}'")
    
    if action not in VALID_ACTIONS:
        return f"Error: action must be one of {VALID_ACTIONS}. Got: '{action}'"
        
    device_id = _resolve_device_id(room)
    if not device_id:
        available = ", ".join(DEVICE_MAPPING.keys())
        return f"Error: unknown device '{room}'. Available: {available}"
        
    success = _send_command(device_id, action)
    if success:
        return f"OK: Persiana '{room}' ({device_id}) → acción '{action}' ejecutada correctamente."
    else:
        return f"Error: No se pudo enviar '{action}' a '{room}' ({device_id}). Revisa los logs del servidor."

@mcp.tool()
def set_all_blinds_state(action: ActionType) -> str:
    """Sube, baja o detiene TODAS las persianas de la casa a la vez.

    IMPORTANTE - Significado de cada acción:
      - 'on'   = SUBIR todas las persianas
      - 'off'  = BAJAR todas las persianas
      - 'stop' = DETENER todas las persianas

    Args:
        action: Comando a enviar a todas las persianas: 'on' (subir), 'off' (bajar), 'stop' (detener).
    """
    logger.info(f"Command received: set_all_blinds_state action='{action}'")
    
    if action not in VALID_ACTIONS:
        return f"Error: action must be one of {VALID_ACTIONS}. Got: '{action}'"
        
    seen = set()
    errors = []
    
    for name, device_id in DEVICE_MAPPING.items():
        if device_id in seen:
            continue
        seen.add(device_id)
        
        success = _send_command(device_id, action)
        if not success:
            errors.append(name)
            
    if errors:
        return f"Error: Acción '{action}' falló para {len(errors)} dispositivos: {', '.join(errors)}"
        
    return f"OK: Acción '{action}' enviada a TODAS las persianas correctamente."

if __name__ == "__main__":
    logger.info(f"Starting Domotics MCP Server. API_URL={API_URL}")
    mcp.run(transport="sse", host="0.0.0.0", port=8000)
