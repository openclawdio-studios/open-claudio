# ── Stage 1: Build React SPA ──────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN npm install --silent
COPY frontend/ .
RUN npm run build
# Output lands in ../backend/static (relative to frontend/) = /app/backend/static

# ── Stage 2: Python FastAPI backend ───────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn[standard] sqlalchemy[asyncio] asyncpg greenlet httpx python-multipart
COPY backend/ .
# Bring in the built React SPA
COPY --from=builder /app/backend/static ./static
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8088"]
