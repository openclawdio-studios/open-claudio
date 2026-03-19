import os
import requests
from datetime import datetime
from typing import Dict, Any

def get_time() -> str:
    """Get the current system time."""
    return str(datetime.now())

def read_file(path: str) -> str:
    """Read a file from disk and return its content (up to 2000 chars)."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()[:2000]
    except Exception as e:
        return f"Error reading file {path}: {str(e)}"

def list_files(path: str = ".") -> str:
    """List files in the specified directory."""
    try:
        files = os.listdir(path)
        return "\n".join(files)
    except Exception as e:
        return f"Error listing directory {path}: {str(e)}"

def http_get(url: str) -> str:
    """Fetch a web URL and return the text content (up to 2000 chars)."""
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.text[:2000]
    except Exception as e:
        return f"Error fetching {url}: {str(e)}"

# Local tools dictionary used to bind functions and schema
LOCAL_TOOLS = {
    "get_time": {
        "description": "get current system time",
        "function": get_time,
        "capabilities": ["utility", "time"],
        "schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    "read_file": {
        "description": "read a file from disk. input: {\"path\":\"file\"}",
        "function": read_file,
        "capabilities": ["server", "file_system"],
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The path of the file to read"}
            },
            "required": ["path"]
        }
    },
    "list_files": {
        "description": "list files in directory. input: {\"path\":\"dir\"}",
        "function": list_files,
        "capabilities": ["server", "file_system"],
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The directory path"}
            },
            "required": ["path"]
        }
    },
    "http_get": {
        "description": "fetch a web url. input: {\"url\":\"http://...\"}",
        "function": http_get,
        "capabilities": ["server", "http", "utility"],
        "schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"}
            },
            "required": ["url"]
        }
    }
}

# Capability tags for ALL tools in the system (local + known MCP tools).
# Used by the planner for capability-based routing and by the executor for
# tool metadata enrichment. MCP tool capabilities are defined here since the
# MCP protocol does not carry capability metadata.
TOOL_CAPABILITIES: Dict[str, list] = {
    # Local tools
    "get_time":          ["utility", "time"],
    "read_file":         ["server", "file_system"],
    "list_files":        ["server", "file_system"],
    "http_get":          ["server", "http", "utility"],
    # MCP — domotics
    "set_blinds_state":      ["home_automation", "blinds"],
    "set_all_blinds_state":  ["home_automation", "blinds"],
    "fermax_open_door":      ["home_automation", "door_control"],
    # MCP — intercom
    "get_fermax_user_info":   ["intercom", "account"],
    "get_fermax_device_info": ["intercom", "device"],
    "get_fermax_history":     ["intercom", "history"],
    # MCP — knowledge / RAG
    "rag_search":        ["knowledge", "search"],
    "rag_ingest":        ["knowledge", "ingestion"],
    "rag_ingest_file":   ["knowledge", "ingestion"],
    "rag_delete_source": ["knowledge", "management"],
    "rag_list_sources":  ["knowledge", "management"],
}
