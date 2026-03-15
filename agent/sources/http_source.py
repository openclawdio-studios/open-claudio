import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

from event_queue import Event, get_queue

logger = logging.getLogger("HTTPSource")

HTTP_PORT = int(os.getenv("HTTP_EVENT_PORT", "8080"))
HTTP_SECRET = os.getenv("HTTP_EVENT_SECRET", "")

app = FastAPI(
    title="Open-Claudio Event API",
    description="Webhook endpoint — POST events to be processed by the agent.",
    version="1.0",
)


class EventRequest(BaseModel):
    event_type: str = "command"
    topic: str = "http/webhook"
    payload: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None


@app.post("/event", summary="Submit an event to the agent")
async def receive_event(
    body: EventRequest,
    authorization: Optional[str] = Header(None),
):
    if HTTP_SECRET:
        if authorization != f"Bearer {HTTP_SECRET}":
            raise HTTPException(status_code=401, detail="Unauthorized")

    event = Event(
        source="http",
        event_type=body.event_type,
        topic=body.topic,
        payload=body.payload,
        timestamp=datetime.now(),
        metadata=body.metadata or {},
    )

    await get_queue().put(event)
    logger.info(f"HTTP <- topic='{body.topic}' payload={body.payload}")
    return {"status": "queued", "topic": body.topic, "event_type": body.event_type}


@app.get("/health", summary="Health check")
async def health():
    return {"status": "ok", "service": "open-claudio-event-api"}


class HTTPSource:
    def __init__(self, port: int = HTTP_PORT):
        self.port = port

    async def run(self):
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=self.port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        logger.info(f"HTTPSource listening on port {self.port}")
        await server.serve()
