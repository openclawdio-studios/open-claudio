"""
Goals router — read-only endpoint exposing the Goal Engine's goal list.

Reads goals.json directly (shared path with the agent container via volume).
No live GoalStore reference is needed here — the dashboard only observes.
"""

import json
import os
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/goals", tags=["goals"])

# Path to goals.json — matches the agent container's working directory.
# Override via GOALS_PATH env var if the volume mount point differs.
_GOALS_PATH = os.getenv("GOALS_PATH", "/app/goals.json")


def _load_goals() -> List[Dict[str, Any]]:
    try:
        with open(_GOALS_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read goals.json: {e}")


@router.get("")
async def list_goals(
    status: Optional[str] = Query(None, description="Filter by status: pending, active, done, failed"),
    goal_type: Optional[str] = Query(None, description="Filter by type: reactive, user"),
):
    """
    List all goals with their current status.

    Returns a read-only snapshot of goals.json.
    Reflects the state as of the last GoalStore.save() call by the agent.
    """
    goals = _load_goals()

    if status:
        goals = [g for g in goals if g.get("status") == status]
    if goal_type:
        goals = [g for g in goals if g.get("goal_type") == goal_type]

    # Return a clean projection — no internal fields needed by the UI
    return [
        {
            "id":                  g.get("id"),
            "description":         g.get("description"),
            "goal_type":           g.get("goal_type"),
            "status":              g.get("status"),
            "priority":            g.get("priority"),
            "desired_state":       g.get("desired_state", {}),
            "attempts":            g.get("attempts", 0),
            "fail_count":          g.get("fail_count", 0),
            "bootstrap_attempted": g.get("bootstrap_attempted", False),
            "created_at":          g.get("created_at"),
            "last_update":         g.get("last_update"),
        }
        for g in goals
    ]


@router.get("/{goal_id}")
async def get_goal(goal_id: str):
    """Return a single goal by ID."""
    goals = _load_goals()
    for g in goals:
        if g.get("id") == goal_id:
            return g
    raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found")
