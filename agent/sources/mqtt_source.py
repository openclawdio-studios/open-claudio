import asyncio
import json
import logging
import os
from datetime import datetime
from typing import List, Optional

import aiomqtt

from event_queue import Event, get_queue
from event_routes import EVENT_ROUTES

logger = logging.getLogger("MQTTSource")

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME") or None
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD") or None
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "open-claudio-agent")


def _mqtt_topics_from_routes() -> List[str]:
    """Extract MQTT-relevant topics from EVENT_ROUTES (exclude logical/non-MQTT topics)."""
    logical_prefixes = ("telegram/", "http/")
    return [
        r.topic for r in EVENT_ROUTES
        if not any(r.topic.startswith(p) for p in logical_prefixes)
    ]


def _classify_event_type(topic: str) -> str:
    parts = topic.split("/")
    return parts[-1] if parts else "unknown"


def _parse_payload(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode())
        if isinstance(data, dict):
            return data
        if isinstance(data, str):
            return {"text": data}
        return {"value": data}
    except (json.JSONDecodeError, UnicodeDecodeError):
        text = raw.decode(errors="replace")
        return {"text": text, "raw": text}


class MQTTSource:
    def __init__(
        self,
        host: str = MQTT_HOST,
        port: int = MQTT_PORT,
        username: Optional[str] = MQTT_USERNAME,
        password: Optional[str] = MQTT_PASSWORD,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._running = False

    async def run(self):
        queue = get_queue()
        self._running = True
        topics = _mqtt_topics_from_routes()

        logger.info(f"MQTTSource connecting to {self.host}:{self.port}")
        logger.info(f"Subscribing to: {topics}")

        while self._running:
            try:
                async with aiomqtt.Client(
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    identifier=MQTT_CLIENT_ID,
                ) as client:
                    for topic in topics:
                        await client.subscribe(topic)

                    async for message in client.messages:
                        topic_str = str(message.topic)
                        payload = _parse_payload(message.payload)

                        event = Event(
                            source="mqtt",
                            event_type=_classify_event_type(topic_str),
                            topic=topic_str,
                            payload=payload,
                            timestamp=datetime.now(),
                            metadata={
                                "qos": message.qos,
                                "retain": message.retain,
                            },
                        )
                        logger.info(f"MQTT <- {topic_str}: {payload}")
                        await queue.put(event)

            except aiomqtt.MqttError as e:
                logger.error(f"MQTT connection error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"MQTTSource unexpected error: {e}. Retrying in 5s...")
                await asyncio.sleep(5)

    def stop(self):
        self._running = False
