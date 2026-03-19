import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from db import recorder
from event_queue import Event, get_queue

logger = logging.getLogger("HTTPSource")

HTTP_PORT = int(os.getenv("HTTP_EVENT_PORT", "8080"))
HTTP_SECRET = os.getenv("HTTP_EVENT_SECRET", "")

if not HTTP_SECRET:
    raise RuntimeError(
        "HTTP_EVENT_SECRET is not set. "
        "The webhook endpoint must be protected by a secret token. "
        "Set HTTP_EVENT_SECRET in your .env file before enabling HTTP_EVENT_ENABLED=true."
    )

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


class QueryRequest(BaseModel):
    message: str
    source: str = "web"


@app.post("/query", summary="Send a query and wait for the agent response (synchronous)")
async def query_agent(
    body: QueryRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    if authorization != f"Bearer {HTTP_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # ── Quota check ───────────────────────────────────────────────────────────
    if x_user_id:
        allowed, used, limit = await recorder.check_user_quota(x_user_id)
        if not allowed:
            tomorrow = (
                datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                + timedelta(days=1)
            )
            return JSONResponse(
                status_code=429,
                content={
                    "status": "quota_exceeded",
                    "error": f"Daily token quota exceeded ({used:,} / {limit:,} tokens used).",
                    "tokens_used": used,
                    "tokens_limit": limit,
                    "reset_at": tomorrow.isoformat(),
                },
            )

    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()

    async def reply_fn(result: str):
        if not future.done():
            future.set_result(result)

    event = Event(
        source="web",
        event_type="query",
        topic="http/webhook",
        payload={"text": body.message},
        timestamp=datetime.now(),
        metadata={"source": body.source, "user_id": x_user_id},
        reply_fn=reply_fn,
    )

    await get_queue().put(event)
    logger.info(f"HTTP /query <- message='{body.message[:60]}'")

    try:
        result = await asyncio.wait_for(asyncio.shield(future), timeout=120.0)
        return {"status": "ok", "response": result}
    except asyncio.TimeoutError:
        return JSONResponse(
            status_code=408,
            content={"status": "timeout", "response": "Agent did not respond within 120 seconds."},
        )


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
