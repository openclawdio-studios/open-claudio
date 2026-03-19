import os
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from db.models import User

router = APIRouter(prefix="/api/chat", tags=["chat"])

AGENT_URL = os.getenv("AGENT_QUERY_URL", "http://agent:8080/query")
HTTP_EVENT_SECRET = os.getenv("HTTP_EVENT_SECRET", "")


class ChatRequest(BaseModel):
    message: str
    source: str = "web"


@router.post("")
async def chat(body: ChatRequest, user: User = Depends(get_current_user)):
    if not HTTP_EVENT_SECRET:
        raise HTTPException(500, "HTTP_EVENT_SECRET not configured")
    async with httpx.AsyncClient(timeout=130.0) as client:
        try:
            resp = await client.post(
                AGENT_URL,
                json={"message": body.message, "source": body.source},
                headers={
                    "Authorization": f"Bearer {HTTP_EVENT_SECRET}",
                    "X-User-Id": str(user.id),
                },
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            raise HTTPException(408, "Agent timeout")
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, e.response.text)
