import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import traces, analytics, events, tools, rag, admin
from chat import router as chat_router

app = FastAPI(title="Open-Claudio Dashboard", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(traces.router)
app.include_router(analytics.router)
app.include_router(events.router)
app.include_router(tools.router)
app.include_router(rag.router)
app.include_router(admin.router)
app.include_router(chat_router)

# Serve React SPA — must come last
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
