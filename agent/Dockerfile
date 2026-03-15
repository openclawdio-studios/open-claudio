FROM alpine:latest
WORKDIR /app
# gcc + musl-dev needed for greenlet (SQLAlchemy asyncio) on Alpine
RUN apk add --no-cache python3 py3-pip gcc musl-dev python3-dev libffi-dev
# Create a venv since alpine might block global pip installs
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-u", "main.py"]
