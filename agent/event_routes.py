from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class EventRoute:
    topic: str                  # MQTT-style pattern (supports # and +) or exact logical topic
    agent: Optional[str]        # None = PlannerAgent decides
    task_template: str          # supports {topic}, {payload}, and any {key} from payload
    description: str = ""


def match_topic(pattern: str, topic: str) -> bool:
    """Match an MQTT-style topic pattern against a concrete topic string."""
    def _match(pp, tp):
        if not pp and not tp:
            return True
        if pp and pp[0] == "#":
            return True
        if not pp or not tp:
            return False
        if pp[0] == "+" or pp[0] == tp[0]:
            return _match(pp[1:], tp[1:])
        return False
    return _match(pattern.split("/"), topic.split("/"))


def find_route(topic: str, event_type: str, routes: List[EventRoute]) -> Optional[EventRoute]:
    """Find the first matching route for a given topic or event_type."""
    for route in routes:
        if match_topic(route.topic, topic):
            return route
    return None


EVENT_ROUTES: List[EventRoute] = [
    EventRoute(
        topic="telegram/chat",
        agent=None,
        task_template="{text}",
        description="Free-text messages from Telegram — Planner decides the agent",
    ),
    EventRoute(
        topic="http/webhook",
        agent=None,
        task_template="{text}",
        description="HTTP webhook commands — Planner decides the agent",
    ),
    EventRoute(
        topic="claudio/command",
        agent=None,
        task_template="{text}",
        description="Generic MQTT command topic — text is sent directly to Planner",
    ),
    EventRoute(
        topic="home/sensors/flood/#",
        agent="home",
        task_template=(
            "CRITICAL ALERT: Flood/water leak detected at sensor '{topic}'. "
            "Execute emergency protocol immediately: close water valve if possible, notify user."
        ),
        description="Flood sensor → home agent emergency protocol",
    ),
    EventRoute(
        topic="home/sensors/motion/#",
        agent="home",
        task_template="Motion detected at '{topic}': {payload}. Take appropriate action if needed.",
        description="Motion sensor events → home agent",
    ),
    EventRoute(
        topic="home/door/bell",
        agent="home",
        task_template="The doorbell has been pressed. Notify the user.",
        description="Doorbell press → home agent",
    ),
    EventRoute(
        topic="server/alert/#",
        agent="server",
        task_template="Server alert on '{topic}': {payload}. Diagnose and report.",
        description="Server alerts → server agent",
    ),
]
