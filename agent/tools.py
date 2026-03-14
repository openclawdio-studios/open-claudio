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
        "schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    "read_file": {
        "description": "read a file from disk. input: {\"path\":\"file\"}",
        "function": read_file,
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
        "schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"}
            },
            "required": ["url"]
        }
    }
}
