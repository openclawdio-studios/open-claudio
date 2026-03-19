"""
Goal — data model and persistence layer for the Goal Engine.

Goals represent desired system states that the agent autonomously works toward.
GoalStore is designed as an interface-compatible class so it can be swapped
to a DB-backed implementation later without changing call sites.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("GoalStore")

_GOALS_PATH = "goals.json"

# ---------------------------------------------------------------------------
# Goal types
# ---------------------------------------------------------------------------

GOAL_TYPE_REACTIVE = "reactive"       # created by event, executed once, then done/failed
GOAL_TYPE_USER = "user"               # explicitly created by user via CLI/Telegram

# ---------------------------------------------------------------------------
# Goal status values
# ---------------------------------------------------------------------------

STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

# ---------------------------------------------------------------------------
# Predefined desired-state templates (GOAP)
# ---------------------------------------------------------------------------
# Each key maps to a state dict that the GoalEngine checks against ctx.state.
# Keys use the format "device.location" (e.g. "blinds.salon").

GOAL_TEMPLATES: Dict[str, Dict[str, str]] = {
    "secure_house": {
        "door.main": "locked",
        "blinds.all": "closed",
    },
    "open_house": {
        "blinds.all": "open",
    },
}


# ---------------------------------------------------------------------------
# Goal dataclass
# ---------------------------------------------------------------------------

@dataclass
class Goal:
    """
    Represents a persistent, autonomous objective.

    Fields
    ------
    id            : unique identifier (UUID or user-supplied slug)
    description   : human-readable description of what needs to happen
    goal_type     : "reactive" | "user"
    priority      : float — higher value = higher urgency (dynamic)
    status        : pending | active | done | failed
    desired_state : dict of state keys → expected values (GOAP)
    context       : arbitrary metadata (event that triggered it, user id, etc.)
    created_at    : unix timestamp
    last_update   : unix timestamp
    attempts      : total execution attempts
    fail_count    : consecutive failures since last success
    bootstrap_attempted : True after the first execution attempt in cold start
    """

    id: str
    description: str
    goal_type: str = GOAL_TYPE_REACTIVE
    priority: float = 1.0
    status: str = STATUS_PENDING
    desired_state: Dict[str, str] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_update: float = field(default_factory=time.time)
    attempts: int = 0
    fail_count: int = 0
    bootstrap_attempted: bool = False

    # ------------------------------------------------------------------
    # Priority helpers
    # ------------------------------------------------------------------

    def compute_priority(self) -> float:
        """
        Dynamic priority: base + age urgency.
        Older goals get progressively more urgent so nothing starves.
        """
        age_hours = (time.time() - self.created_at) / 3600
        return self.priority + age_hours

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Goal":
        return Goal(**{k: v for k, v in d.items() if k in Goal.__dataclass_fields__})


# ---------------------------------------------------------------------------
# GoalStore
# ---------------------------------------------------------------------------

class GoalStore:
    """
    In-memory goal registry with goals.json persistence.

    Interface is intentionally DB-compatible so it can be backed by
    SQLAlchemy later without changing call sites.
    """

    def __init__(self, path: str = _GOALS_PATH):
        self._path = path
        self._goals: Dict[str, Goal] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, goal: Goal) -> None:
        """Add or replace a goal."""
        goal.last_update = time.time()
        self._goals[goal.id] = goal
        logger.info(f"GoalStore: added goal '{goal.id}' [{goal.goal_type}] priority={goal.priority}")

    def get(self, goal_id: str) -> Optional[Goal]:
        return self._goals.get(goal_id)

    def update(self, goal: Goal) -> None:
        """Persist in-place changes to a goal object."""
        goal.last_update = time.time()
        self._goals[goal.id] = goal

    def remove(self, goal_id: str) -> None:
        self._goals.pop(goal_id, None)

    def all(self) -> List[Goal]:
        return list(self._goals.values())

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_active(self) -> List[Goal]:
        """Goals that still need processing, sorted by dynamic priority (desc)."""
        active = [
            g for g in self._goals.values()
            if g.status in (STATUS_PENDING, STATUS_ACTIVE)
        ]
        active.sort(key=lambda g: g.compute_priority(), reverse=True)
        return active

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Optional[str] = None) -> None:
        p = path or self._path
        try:
            data = [g.to_dict() for g in self._goals.values()]
            with open(p, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"GoalStore: saved {len(data)} goal(s) to {p}")
        except Exception as e:
            logger.error(f"GoalStore.save() failed: {e}")

    def load(self, path: Optional[str] = None) -> None:
        p = path or self._path
        try:
            with open(p) as f:
                data = json.load(f)
            for d in data:
                goal = Goal.from_dict(d)
                # Reset transient active state on restart — goals resume as pending
                if goal.status == STATUS_ACTIVE:
                    goal.status = STATUS_PENDING
                self._goals[goal.id] = goal
            logger.info(f"GoalStore: loaded {len(self._goals)} goal(s) from {p}")
        except FileNotFoundError:
            logger.info("GoalStore: no goals.json found, starting fresh.")
        except Exception as e:
            logger.warning(f"GoalStore.load() failed ({e}), starting fresh.")

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @staticmethod
    def make_goal(
        description: str,
        goal_type: str = GOAL_TYPE_REACTIVE,
        priority: float = 1.0,
        template: Optional[str] = None,
        desired_state: Optional[Dict[str, str]] = None,
        context: Optional[Dict[str, Any]] = None,
        goal_id: Optional[str] = None,
    ) -> Goal:
        """
        Convenience factory. Merges a named template with an optional
        override desired_state.
        """
        state: Dict[str, str] = {}
        if template and template in GOAL_TEMPLATES:
            state.update(GOAL_TEMPLATES[template])
        if desired_state:
            state.update(desired_state)

        return Goal(
            id=goal_id or str(uuid.uuid4()),
            description=description,
            goal_type=goal_type,
            priority=priority,
            status=STATUS_PENDING,
            desired_state=state,
            context=context or {},
        )
