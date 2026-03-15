from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Optional
import asyncio


@dataclass
class Event:
    source: str          # "telegram" | "mqtt" | "http" | "cli"
    event_type: str      # "message" | "motion_detected" | "flood_detected" | etc.
    topic: str           # MQTT topic or logical topic (e.g. "telegram/chat")
    payload: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    reply_fn: Optional[Callable[[str], Any]] = None  # async callback to reply to sender


_queue: Optional[asyncio.Queue] = None


def get_queue() -> asyncio.Queue:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue
