from fastmcp import FastMCP
import uvicorn
import logging
import os
import requests
import unicodedata

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_domotics")

API_URL = os.getenv("PERSIANAS_API_URL", "https://northr3nd.duckdns.org")
API_TOKEN = os.getenv("PERSIANAS_API_TOKEN", None)

DEVICE_MAPPING = {
    'Ventana Hab. Principal': 'ZWayVDev_zway_3-0-38',
    'Puerta Hab. Principal':  'ZWayVDev_zway_8-0-38',
    'Ventana Salon':          'ZWayVDev_zway_4-0-38',
    'Ventana Salón':          'ZWayVDev_zway_4-0-38',
    'Puerta Salon':           'ZWayVDev_zway_2-0-38',
    'Puerta Salón':           'ZWayVDev_zway_2-0-38',
    'Ventana Ordenadores':    'ZWayVDev_zway_7-0-38',
    'Ventana Hab. Jaume/Edu': 'ZWayVDev_zway_9-0-38',
}

VALID_ACTIONS = ['on', 'off', 'stop']

def _normalize(s: str) -> str:
    return unicodedata.normalize('NFD', s.lower()).encode('ascii', 'ignore').decode('utf-8')

def _resolve_device_id(device: str) -> str | None:
    if device in DEVICE_MAPPING:
        return DEVICE_MAPPING[device]
    
    normalized_device = _normalize(device)
    for k, v in DEVICE_MAPPING.items():
        if _normalize(k) == normalized_device:
            return v
            
    if device.startswith('ZWayVDev_'):
        return device
    return None

def _send_command(device_id: str, action: str) -> bool:
    url = f"{API_URL}/api/devices/{device_id}/command/{action}"
    headers = {'Content-Type': 'application/json'}
    if API_TOKEN:
        headers['Authorization'] = f"Bearer {API_TOKEN}"
        
    try:
        res = requests.post(url, headers=headers, timeout=10)
        res.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Error calling {url}: {e}")
        return False

# Create a FastMCP server
mcp = FastMCP("domotics")

@mcp.tool()
def set_blinds_state(room: str, action: str) -> str:
    """Control the blinds in a specific room.
    
    Args:
        room: The name of the room or ZWave ID (e.g., 'Ventana Salon', 'Puerta Hab. Principal')
        action: The action to perform ('on' for open/subir, 'off' for close/bajar, 'stop' for deteniendo)
    """
    logger.info(f"Command received: set_blinds_state in {room} to {action}")
    
    if action not in VALID_ACTIONS:
        return f"Error: action must be one of {VALID_ACTIONS}"
        
    device_id = _resolve_device_id(room)
    if not device_id:
        available = ", ".join(list(set(DEVICE_MAPPING.keys())))
        return f"Error: unknown device '{room}'. Available: {available}"
        
    success = _send_command(device_id, action)
    if success:
        return f"Success: Blinds in {room} ({device_id}) received action {action}."
    else:
        return f"Error: Failed to send action {action} to {room} ({device_id}). Check server logs."

@mcp.tool()
def set_all_blinds_state(action: str) -> str:
    """Control ALL blinds in the house simultaneously.
    
    Args:
        action: The action to perform ('on' for open/subir, 'off' for close/bajar, 'stop' for deteniendo)
    """
    logger.info(f"Command received: set_all_blinds_state to {action}")
    
    if action not in VALID_ACTIONS:
        return f"Error: action must be one of {VALID_ACTIONS}"
        
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
        return f"Error: Action '{action}' failed for {len(errors)} devices: {', '.join(errors)}"
        
    return f"Success: Action '{action}' sent to ALL blinds."

if __name__ == "__main__":
    logger.info(f"Starting Domotics MCP Server. API_URL={API_URL}")
    mcp.run(transport="sse", host="0.0.0.0", port=8000)
