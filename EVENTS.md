# Open-Claudio Event-Driven Architecture

This document describes the event-driven layer built on top of the hierarchical multi-agent system.
The agent can now receive commands and sensor data from three sources: MQTT, Telegram, and HTTP webhooks.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Open-Claudio Agent Container                          │
│                                                                              │
│   ┌─────────────┐   ┌──────────────────┐   ┌──────────────────────────────┐ │
│   │ MQTTSource  │   │ TelegramSource   │   │       HTTPSource             │ │
│   │             │   │                  │   │   FastAPI /event endpoint    │ │
│   │ aiomqtt     │   │ aiogram v3 bot   │   │   uvicorn on port 8080       │ │
│   │ subscriber  │   │ long-polling     │   │                              │ │
│   └──────┬──────┘   └───────┬──────────┘   └──────────────┬───────────────┘ │
│          │                  │                              │                 │
│          └──────────────────┴──────────────────────────────┘                 │
│                             │  asyncio.Queue (shared)                        │
│                             ▼                                                │
│                    ┌─────────────────┐                                       │
│                    │  EventWorker    │  sequential dispatch                  │
│                    │                 │  (no parallel LLM calls)              │
│                    │  find_route()   │                                       │
│                    └────────┬────────┘                                       │
│                             │  route.agent or planner                        │
│          ┌──────────────────┼────────────────────────────────┐               │
│          ▼                  ▼                                ▼               │
│   ┌─────────────┐   ┌──────────────┐   ┌──────────────────────────────────┐ │
│   │  HomeAgent  │   │ ServerAgent  │   │  PlannerAgent                    │ │
│   │  (blinds,   │   │  (files,     │   │  (decomposes task and routes to  │ │
│   │   door)     │   │   HTTP)      │   │   the right domain agent)        │ │
│   └─────────────┘   └──────────────┘   └──────────────────────────────────┘ │
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  reply_fn callback — sends agent result back to originating source  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘

External services:
  Mosquitto broker  (port 1883, eclipse-mosquitto:2 container)
  Telegram Bot API  (cloud)
  Any HTTP client   (curl, sensors, scripts)
```

### Data flow

1. A source (MQTT/Telegram/HTTP) receives an external signal.
2. The source wraps it in an `Event` dataclass and places it on `asyncio.Queue`.
3. `EventWorker` drains the queue one item at a time and calls `find_route()` against `EVENT_ROUTES`.
4. The matching route specifies which agent to call and how to format the task string.
5. The agent runs its ReAct loop and returns a result string.
6. If `event.reply_fn` is set, the result is sent back to the originator (e.g. the Telegram chat).

---

## Core modules

| File | Purpose |
|------|---------|
| `agent/event_queue.py` | `Event` dataclass + shared `asyncio.Queue` singleton |
| `agent/event_routes.py` | `EventRoute` dataclass, `EVENT_ROUTES` config, `match_topic()` |
| `agent/event_worker.py` | Queue consumer — dispatches events to agents |
| `agent/sources/mqtt_source.py` | `aiomqtt` subscriber |
| `agent/sources/telegram_source.py` | `aiogram` v3 bot |
| `agent/sources/http_source.py` | `FastAPI` + `uvicorn` webhook server |

---

## Environment Variables

### MQTT Source

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MQTT_HOST` | `mosquitto` | Yes (to enable MQTT) | Hostname/IP of the MQTT broker. If unset, MQTTSource is disabled. |
| `MQTT_PORT` | `1883` | No | TCP port of the MQTT broker. |
| `MQTT_USERNAME` | _(empty)_ | No | Username for broker authentication. Leave unset for anonymous. |
| `MQTT_PASSWORD` | _(empty)_ | No | Password for broker authentication. |
| `MQTT_CLIENT_ID` | `open-claudio-agent` | No | MQTT client identifier. Must be unique per broker. |

### Telegram Source

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | _(empty)_ | Yes (to enable Telegram) | Bot token from @BotFather. If unset, TelegramSource is disabled. |
| `TELEGRAM_ALLOWED_CHAT_IDS` | _(empty)_ | No | Comma-separated list of allowed chat IDs (e.g. `123456,-987654`). If unset, all chats are accepted — set this in production. |

### HTTP Source

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `HTTP_EVENT_ENABLED` | `false` | Yes (set to `true`) | Must be `true` to start the HTTP webhook server. |
| `HTTP_EVENT_PORT` | `8080` | No | Port the FastAPI server listens on. Also exposed in docker-compose. |
| `HTTP_EVENT_SECRET` | _(empty)_ | No | If set, every POST to `/event` must include `Authorization: Bearer <secret>`. |

---

## Telegram Setup — Step by Step

### 1. Create a bot with @BotFather

1. Open Telegram and search for `@BotFather`.
2. Send `/newbot`.
3. Follow the prompts: enter a display name, then a unique `@username` (must end in `bot`).
4. Copy the token shown — it looks like `7123456789:AAF_abc...XYZ`.

### 2. Get your chat ID

Start a conversation with your bot (send `/start`), then run:

```bash
curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates"
```

Look for `"chat":{"id":` in the JSON response. That number is your chat ID.
For group chats, the ID is negative (e.g. `-1001234567890`).

### 3. Set environment variables

Add to your `.env` file:

```env
TELEGRAM_BOT_TOKEN=7123456789:AAF_abcXYZ
TELEGRAM_ALLOWED_CHAT_IDS=123456789
```

Or for multiple users/groups:

```env
TELEGRAM_ALLOWED_CHAT_IDS=123456789,-1001234567890
```

### 4. Enable in docker-compose

Uncomment the relevant lines in `docker-compose.yml`:

```yaml
environment:
  - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
  - TELEGRAM_ALLOWED_CHAT_IDS=${TELEGRAM_ALLOWED_CHAT_IDS}
```

### 5. Test

Send any message to your bot. The bot will pass it through the PlannerAgent and reply.

Commands supported:
- `/start` — greeting message
- Any free text — processed by the agent

---

## MQTT Usage Examples

The Mosquitto broker is accessible at `localhost:1883` (from the host) or `mosquitto:1883` (from other containers).

### Install mosquitto-clients (for testing)

```bash
# Ubuntu/Debian
sudo apt install mosquitto-clients

# macOS
brew install mosquitto
```

### Publish a command to the agent

```bash
# Generic command — routed to PlannerAgent
mosquitto_pub -h localhost -p 1883 \
  -t "claudio/command" \
  -m '{"text": "Close all the blinds"}'

# Or plain text
mosquitto_pub -h localhost -p 1883 \
  -t "claudio/command" \
  -m "Close all the blinds"
```

### Simulate a flood sensor alert

```bash
mosquitto_pub -h localhost -p 1883 \
  -t "home/sensors/flood/bathroom" \
  -m '{"value": 1, "sensor": "bathroom_floor"}'
```

This triggers the HomeAgent with: `CRITICAL ALERT: Flood/water leak detected at sensor 'home/sensors/flood/bathroom'. Execute emergency protocol immediately...`

### Simulate a motion detection event

```bash
mosquitto_pub -h localhost -p 1883 \
  -t "home/sensors/motion/living_room" \
  -m '{"value": 1, "zone": "living_room"}'
```

### Simulate a doorbell press

```bash
mosquitto_pub -h localhost -p 1883 \
  -t "home/door/bell" \
  -m '{"pressed": true}'
```

### Simulate a server alert

```bash
mosquitto_pub -h localhost -p 1883 \
  -t "server/alert/disk" \
  -m '{"level": "warning", "message": "Disk usage above 90%", "host": "nas01"}'
```

### Subscribe to all topics (for debugging)

```bash
mosquitto_sub -h localhost -p 1883 -t "#" -v
```

---

## HTTP Webhook Examples

The HTTP source exposes a REST API on port `8080`.

### Health check

```bash
curl http://localhost:8080/health
# {"status":"ok","service":"open-claudio-event-api"}
```

### Submit a generic command

```bash
curl -X POST http://localhost:8080/event \
  -H "Content-Type: application/json" \
  -d '{"payload": {"text": "What time is it?"}}'
```

### Submit a command with explicit topic

```bash
curl -X POST http://localhost:8080/event \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "command",
    "topic": "http/webhook",
    "payload": {"text": "Open the front door"}
  }'
```

### With authentication (when HTTP_EVENT_SECRET is set)

```bash
curl -X POST http://localhost:8080/event \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer my-secret-token" \
  -d '{"payload": {"text": "Close all blinds"}}'
```

### Simulate a flood alert via HTTP

```bash
curl -X POST http://localhost:8080/event \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "flood_detected",
    "topic": "home/sensors/flood/kitchen",
    "payload": {"value": 1, "sensor": "kitchen_sink"}
  }'
```

### Interactive API docs

When HTTPSource is running, browse to `http://localhost:8080/docs` for the Swagger UI.

---

## EVENT_ROUTES Configuration

Routes are defined in `agent/event_routes.py` as a list of `EventRoute` objects.

```python
@dataclass
class EventRoute:
    topic: str          # MQTT-style pattern or logical topic
    agent: Optional[str]  # None = PlannerAgent, or "home", "server", "intercom", "utility"
    task_template: str  # Jinja-like format string
    description: str = ""
```

### Topic pattern syntax

The topic system follows the MQTT wildcard convention:

| Pattern | Matches | Does not match |
|---------|---------|----------------|
| `home/door/bell` | `home/door/bell` only | `home/door/bell/extra` |
| `home/sensors/motion/+` | `home/sensors/motion/kitchen` | `home/sensors/motion/kitchen/sub` |
| `home/sensors/flood/#` | `home/sensors/flood/bathroom`, `home/sensors/flood/a/b/c` | `home/sensors` |
| `server/alert/#` | `server/alert/disk`, `server/alert/cpu/high` | `home/alert/disk` |

- `+` matches exactly one level.
- `#` matches one or more levels (must be the last segment).

### task_template variables

The template string supports Python `.format()` syntax:

| Variable | Value |
|----------|-------|
| `{topic}` | The full concrete MQTT topic (e.g. `home/sensors/flood/bathroom`) |
| `{payload}` | The full payload dict as a string |
| `{text}` | `payload.get("text", str(payload))` — best for text commands |
| `{key}` | Any top-level key from the payload dict |

Example: if payload is `{"level": "warning", "host": "nas01"}` and template is
`"Alert from {host}: {level}"`, the task becomes `"Alert from nas01: warning"`.

### Adding a new route

```python
# In agent/event_routes.py, append to EVENT_ROUTES:
EventRoute(
    topic="home/sensors/temperature/#",
    agent="home",
    task_template="Temperature reading from '{topic}': {value}°C. Log this and alert if above 30.",
    description="Temperature sensor → home agent",
),
```

For topics that should go to the PlannerAgent (free routing), set `agent=None`:

```python
EventRoute(
    topic="claudio/ask",
    agent=None,
    task_template="{text}",
    description="General questions — Planner decides",
),
```

---

## Testing Locally

### Start all services

```bash
cd C:/ws/open-claudio
docker-compose up --build
```

### Start only the broker and agent (skip MCP servers)

```bash
docker-compose up mosquitto agent
```

### Attach to agent CLI (interactive mode)

```bash
docker attach open-claudio-agent
# Type commands at the >> prompt
# Ctrl+P, Ctrl+Q to detach without stopping
```

### Follow agent logs

```bash
docker logs -f open-claudio-agent
```

### End-to-end MQTT test flow

```bash
# Terminal 1: watch agent logs
docker logs -f open-claudio-agent

# Terminal 2: send a command
mosquitto_pub -h localhost -p 1883 -t claudio/command -m '{"text":"What time is it?"}'
```

Expected log output:
```
EventWorker: mqtt → planner | task: 'What time is it?...'
EventWorker: result: It is 14:32 UTC.
```

### End-to-end HTTP test flow

First enable HTTP in docker-compose by uncommenting `HTTP_EVENT_ENABLED=true`, then:

```bash
docker-compose up --build

curl -X POST http://localhost:8080/event \
  -H "Content-Type: application/json" \
  -d '{"payload": {"text": "Are the blinds open?"}}'
```

---

## Adding a New Event Source

Any class with an `async def run(self)` method that pushes `Event` objects to the shared queue can act as a source.

### Example: a simple custom source

```python
# agent/sources/my_custom_source.py
import asyncio
import logging
from datetime import datetime
from event_queue import Event, get_queue

logger = logging.getLogger("MyCustomSource")


class MyCustomSource:
    """Example: polls an external API every 60 seconds."""

    def __init__(self, api_url: str):
        self.api_url = api_url
        self._running = False

    async def run(self):
        import aiohttp
        queue = get_queue()
        self._running = True

        async with aiohttp.ClientSession() as session:
            while self._running:
                try:
                    async with session.get(self.api_url) as resp:
                        data = await resp.json()

                    event = Event(
                        source="my_custom_source",
                        event_type="poll_result",
                        topic="claudio/command",   # reuse an existing route
                        payload={"text": f"Received data: {data}"},
                        timestamp=datetime.now(),
                    )
                    await queue.put(event)
                    logger.info(f"Queued poll result: {data}")
                except Exception as e:
                    logger.error(f"Poll error: {e}")

                await asyncio.sleep(60)

    def stop(self):
        self._running = False
```

### Register it in main.py

In `_build_event_tasks()`, add:

```python
if os.getenv("MY_API_URL"):
    from sources.my_custom_source import MyCustomSource
    tasks.append(MyCustomSource(api_url=os.getenv("MY_API_URL")).run())
    logger.info("MyCustomSource enabled")
```

### Key rules for custom sources

1. Always use `get_queue()` to retrieve the shared queue — never create your own.
2. Set `event.reply_fn` to an async callable if you want the agent result sent back to the user.
3. Choose an existing `topic` from `EVENT_ROUTES` or add a new route for the new topic.
4. Handle your own reconnect/retry logic — the EventWorker will not restart your source.
5. The source runs as an asyncio task; use `await asyncio.sleep()` for polling intervals.

---

## Troubleshooting

### Agent not receiving MQTT messages

- Check `MQTT_HOST` is set in the agent container environment.
- Verify Mosquitto is running: `docker logs open-claudio-mosquitto`.
- Confirm the topic you're publishing to matches a pattern in `EVENT_ROUTES`.
- Use `mosquitto_sub -h localhost -t "#" -v` to verify the message reaches the broker.

### Telegram bot not responding

- Confirm `TELEGRAM_BOT_TOKEN` is correct and the bot has been started (`/start`).
- Check `TELEGRAM_ALLOWED_CHAT_IDS` includes your chat ID.
- Look for errors in `docker logs open-claudio-agent | grep Telegram`.

### HTTP 401 Unauthorized

- You have `HTTP_EVENT_SECRET` set. Include `Authorization: Bearer <your-secret>` in all POST requests.

### "No route for topic" warning

- The published topic does not match any entry in `EVENT_ROUTES`.
- Add a matching route in `agent/event_routes.py` or adjust the published topic.

### Events are queued but never processed

- The EventWorker processes events sequentially. If an agent call is hanging (LLM timeout),
  subsequent events will wait. Check `MAX_STEPS` and LLM connectivity.
