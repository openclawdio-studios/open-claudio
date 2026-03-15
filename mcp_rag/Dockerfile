FROM python:3.11-slim

WORKDIR /app

# Build deps for chromadb native extensions + PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download embedding model into the image — avoids network calls at runtime
# nomic-embed-text-v1.5 requires trust_remote_code=True
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)"

COPY . .

# /data  → ChromaDB persistent storage (Docker volume)
# /docs  → read-only mount for document ingestion
VOLUME ["/data"]

EXPOSE 8002

CMD ["python", "-u", "server.py"]
