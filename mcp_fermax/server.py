import os
import requests
import json
import logging
from fastmcp import FastMCP
from urllib.parse import quote

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_fermax")

# Fetch credentials from environment
USERNAME = os.getenv("FERMAX_USERNAME")
PASSWORD = os.getenv("FERMAX_PASSWORD")

# Constants mapping from the original script
COMMON_HEADERS = {
    'app-version': '3.3.2',
    'accept-language': 'en-ES;q=1.0, es-ES;q=0.9, ru-ES;q=0.8',
    'phone-os': '16.4',
    'user-agent': 'Blue/3.3.2 (com.fermax.bluefermax; build:3; iOS 16.4.0) Alamofire/3.3.2',
    'phone-model': 'iPad14,5',
    'app-build': '3'
}

AUTH_URL = 'https://oauth-pro-duoxme.fermax.io/oauth/token'
AUTH_HEADERS = {
    'Authorization': 'Basic ZHB2N2lxejZlZTVtYXptMWlxOWR3MWQ0MnNseXV0NDhrajBtcDVmdm81OGo1aWg6Yzd5bGtxcHVqd2FoODV5aG5wcnYwd2R2eXp1dGxjbmt3NHN6OTBidWxkYnVsazE=',
    'Content-Type': 'application/x-www-form-urlencoded'
}
AUTH_HEADERS.update(COMMON_HEADERS)

def _auth() -> str:
    """Perform authentication to the Fermax API and return the Bearer token."""
    if not USERNAME or not PASSWORD:
        raise ValueError("FERMAX_USERNAME and FERMAX_PASSWORD must be strictly defined in the environment")
        
    usr = quote(USERNAME)
    pwd = quote(PASSWORD)
    auth_payload = f'grant_type=password&password={pwd}&username={usr}'

    res = requests.post(AUTH_URL, headers=AUTH_HEADERS, data=auth_payload, timeout=10)
    parsed = res.json()
    
    if 'error' in parsed:
        raise RuntimeError(parsed['error_description'])
        
    return parsed['access_token']

def _get_json_headers(access_token: str) -> dict:
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    headers.update(COMMON_HEADERS)
    return headers

def _get_pairings(access_token: str) -> tuple:
    """Fetch the default paired device information."""
    url = 'https://pro-duoxme.fermax.io/pairing/api/v3/pairings/me'
    res = requests.get(url, headers=_get_json_headers(access_token), timeout=10)
    parsed = res.json()
    
    if not parsed:
        raise Exception('No pairings found for the user')
        
    pairing = parsed[0]
    tag = pairing['tag']
    device_id = pairing['deviceId']
    access_door_map = pairing['accessDoorMap']

    access_ids = []
    for d in access_door_map.values():
        if d['visible']:
            access_ids.append(d['accessId'])
            
    return (tag, device_id, access_ids)

# --- Define the FastMCP Server ---
mcp = FastMCP("fermax")

@mcp.tool()
def get_fermax_user_info() -> str:
    """Gets user account information associated with the Fermax intercom profile."""
    try:
        token = _auth()
        url = "https://pro-duoxme.fermax.io/user/api/v1/users/me"
        res = requests.get(url, headers=_get_json_headers(token), timeout=10)
        res.raise_for_status()
        return json.dumps(res.json(), indent=2)
    except Exception as e:
        return f"Error obtaining Fermax user info: {str(e)}"

@mcp.tool()
def get_fermax_device_info() -> str:
    """Gets technical information and status about the primary paired Fermax intercom device."""
    try:
        token = _auth()
        _, device_id, _ = _get_pairings(token)
        url = f"https://pro-duoxme.fermax.io/deviceaction/api/v1/device/{device_id}"
        res = requests.get(url, headers=_get_json_headers(token), timeout=10)
        res.raise_for_status()
        return json.dumps(res.json(), indent=2)
    except Exception as e:
        return f"Error obtaining Fermax device info: {str(e)}"

@mcp.tool()
def get_fermax_history() -> str:
    """Gets the recent history (calls, misses) of the user's Fermax intercom."""
    try:
        token = _auth()
        _, device_id, _ = _get_pairings(token)
        url = f"https://pro-duoxme.fermax.io/services2/api/v1/services/{device_id}"
        res = requests.get(url, headers=_get_json_headers(token), timeout=10)
        res.raise_for_status()
        return json.dumps(res.json(), indent=2)
    except Exception as e:
        return f"Error obtaining Fermax history: {str(e)}"

@mcp.tool()
def fermax_open_door() -> str:
    """Actuates the relay of the Fermax intercom. Use ONLY when the user asks to OPEN the door of the video intercom."""
    try:
        token = _auth()
        tag, device_id, access_ids = _get_pairings(token)
        
        if not access_ids:
            return "Error: No access doors visible in pairing map."
            
        url = f'https://pro-duoxme.fermax.io/deviceaction/api/v1/device/{device_id}/directed-opendoor'
        
        results = []
        # Open all doors returned in access_ids
        for access_id in access_ids:
            payload = json.dumps(access_id)
            res = requests.post(url, headers=_get_json_headers(token), data=payload, timeout=10)
            res.raise_for_status()
            results.append(f"Door {access_id} result: {res.text.strip()}")
            
        return "Success: " + " | ".join(results)
    except Exception as e:
        return f"Error opening Fermax door: {str(e)}"

if __name__ == "__main__":
    logger.info("Starting Fermax MCP Server")
    if not USERNAME or not PASSWORD:
        logger.warning("FERMAX_USERNAME or FERMAX_PASSWORD environment variables are missing! API calls will fail.")
    mcp.run(transport="sse", host="0.0.0.0", port=8001)
