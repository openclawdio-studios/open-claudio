"""
Self-Healing Tool Layer for Open-Claudio.

Provides error classification, repair strategies (retry, LLM parameter correction),
and persistent fix learning so the agent doesn't repeat the same mistakes.
"""

import json
import logging
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("tool_healing")

# ---------------------------------------------------------------------------
# Error types and repair strategies
# ---------------------------------------------------------------------------

ERROR_TYPES = {
    "connection_error",
    "timeout",
    "validation_error",
    "permission_error",
    "tool_not_found",
    "unknown_error",
}

# Maps error type → strategy name
REPAIR_STRATEGIES: Dict[str, str] = {
    "connection_error": "retry",
    "timeout":          "retry",
    "validation_error": "llm_fix",
    "permission_error": "report",
    "tool_not_found":   "report",
    "unknown_error":    "retry_then_report",
}

# Keywords used to auto-classify unstructured error strings
_CLASSIFICATION_KEYWORDS: List[Tuple[str, list]] = [
    ("timeout",          ["timeout", "timed out", "deadline"]),
    ("connection_error", ["connection", "connect", "unreachable", "network", "refused", "dns"]),
    ("permission_error", ["permission", "denied", "unauthorized", "403", "401", "forbidden", "credentials"]),
    ("validation_error", ["validation", "invalid", "unknown device", "not found in", "must be one of",
                          "available_values", "parameter", "expected"]),
    ("tool_not_found",   ["tool not found", "not found on any"]),
]

MAX_HEAL_RETRIES = 2

# ---------------------------------------------------------------------------
# Tool avoidance (based on runtime metrics)
# ---------------------------------------------------------------------------

TOOL_AVOIDANCE_MIN_CALLS = 5    # minimum calls before success_rate is trusted
TOOL_AVOIDANCE_THRESHOLD = 0.8  # below this success_rate the tool is avoided


def should_avoid_tool(mem_ns: dict, tool_name: str) -> tuple:
    """
    Decide whether a tool should be skipped based on its runtime track record.

    Returns
    -------
    (avoid: bool, reason: str)
        avoid  — True if the tool should be skipped this call.
        reason — human-readable explanation (empty string when avoid=False).

    A tool is avoided only when:
      - it has at least TOOL_AVOIDANCE_MIN_CALLS recorded calls (enough data), AND
      - its success_rate is below TOOL_AVOIDANCE_THRESHOLD.
    """
    stats = mem_ns.get("tool_metrics", {}).get(tool_name, {})
    calls = stats.get("calls", 0)

    if calls < TOOL_AVOIDANCE_MIN_CALLS:
        return False, ""  # insufficient data — do not penalise

    errors = stats.get("errors", 0)
    success_rate = (calls - errors) / calls

    if success_rate < TOOL_AVOIDANCE_THRESHOLD:
        return True, (
            f"success_rate={success_rate:.0%} over {calls} calls "
            f"(threshold: {TOOL_AVOIDANCE_THRESHOLD:.0%}, "
            f"min_calls: {TOOL_AVOIDANCE_MIN_CALLS})"
        )
    return False, ""


# ---------------------------------------------------------------------------
# Structured result helpers
# ---------------------------------------------------------------------------

class ToolResult:
    """Normalized tool result — success or structured error."""
    def __init__(self, success: bool, content: str, error_type: Optional[str] = None,
                 raw: Any = None):
        self.success = success
        self.content = content
        self.error_type = error_type
        self.raw = raw  # original parsed dict if JSON

    def __repr__(self):
        if self.success:
            return f"ToolResult(OK, {self.content[:80]})"
        return f"ToolResult(ERROR, type={self.error_type}, {self.content[:80]})"


def parse_tool_result(raw_result: str) -> ToolResult:
    """
    Parse a raw tool response into a ToolResult.
    Handles:
    - JSON with {"status": "error", ...}
    - Plain strings starting with "Error" / "Error:"
    - Everything else = success
    """
    raw_result = raw_result.strip()

    # Try JSON first
    try:
        data = json.loads(raw_result)
        if isinstance(data, dict) and data.get("status") == "error":
            etype = data.get("error_type", "unknown_error")
            msg = data.get("message", raw_result)
            return ToolResult(success=False, content=msg, error_type=etype, raw=data)
        # JSON but not an error
        return ToolResult(success=True, content=raw_result, raw=data)
    except (json.JSONDecodeError, TypeError):
        pass

    # Heuristic: plain-text error strings
    lower = raw_result.lower()
    if lower.startswith("error"):
        etype = classify_error_string(raw_result)
        return ToolResult(success=False, content=raw_result, error_type=etype)

    return ToolResult(success=True, content=raw_result)


def classify_error_string(message: str) -> str:
    """Classify a plain-text error message into an error type using keywords."""
    lower = message.lower()
    for etype, keywords in _CLASSIFICATION_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return etype
    return "unknown_error"


# ---------------------------------------------------------------------------
# Repair strategies
# ---------------------------------------------------------------------------

def get_strategy(error_type: str) -> str:
    """Return the repair strategy for a given error type."""
    return REPAIR_STRATEGIES.get(error_type, "report")


def build_repair_prompt(tool_name: str, arguments: dict, error: ToolResult) -> str:
    """
    Build a prompt asking the LLM to correct tool parameters.
    Includes available_values hint if the MCP server provided them.
    """
    available_hint = ""
    if error.raw and isinstance(error.raw, dict):
        avail = error.raw.get("available_values")
        if avail:
            available_hint = f"\nAllowed values: {json.dumps(avail)}"

    return (
        f"A tool call failed and needs parameter correction.\n\n"
        f"Tool: {tool_name}\n"
        f"Input: {json.dumps(arguments)}\n"
        f"Error type: {error.error_type}\n"
        f"Error message: {error.content}\n"
        f"{available_hint}\n\n"
        f"Respond ONLY with the corrected JSON input object. "
        f"Do not include any explanation, just the raw JSON."
    )


def parse_llm_fix(llm_response: str) -> Optional[dict]:
    """Try to extract a JSON dict from the LLM's correction response."""
    text = llm_response.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Persistent fix memory
# ---------------------------------------------------------------------------

def lookup_known_fix(memory: dict, tool_name: str, arguments: dict) -> Optional[dict]:
    """
    Check if we've previously fixed this exact (tool, wrong_args) combination.
    Returns the corrected arguments if found, None otherwise.
    """
    fixes = memory.get("tool_fixes", [])
    for fix in fixes:
        if fix.get("tool") != tool_name:
            continue
        original = fix.get("original", {})
        # Check if the current args contain the same "wrong" values
        if all(arguments.get(k) == v for k, v in original.items()):
            corrected = dict(arguments)
            corrected.update(fix.get("fixed", {}))
            logger.info(f"Found known fix for '{tool_name}': {original} → {fix.get('fixed')}")
            return corrected
    return None


def record_fix(memory: dict, tool_name: str, original_args: dict, fixed_args: dict):
    """Record a successful fix so we don't repeat the same mistake."""
    if "tool_fixes" not in memory:
        memory["tool_fixes"] = []

    # Find the differing keys
    diff_original = {}
    diff_fixed = {}
    for k in set(list(original_args.keys()) + list(fixed_args.keys())):
        if original_args.get(k) != fixed_args.get(k):
            diff_original[k] = original_args.get(k)
            diff_fixed[k] = fixed_args.get(k)

    if not diff_original:
        return  # Nothing changed

    fix_entry = {
        "tool": tool_name,
        "original": diff_original,
        "fixed": diff_fixed,
        "timestamp": datetime.now().isoformat(),
    }

    # Avoid duplicates
    for existing in memory["tool_fixes"]:
        if existing.get("tool") == tool_name and existing.get("original") == diff_original:
            existing["fixed"] = diff_fixed
            existing["timestamp"] = fix_entry["timestamp"]
            logger.info(f"Updated existing fix for '{tool_name}'")
            return

    memory["tool_fixes"].append(fix_entry)
    logger.info(f"Recorded new fix for '{tool_name}': {diff_original} → {diff_fixed}")


# ---------------------------------------------------------------------------
# Tool metrics (lightweight observability)
# ---------------------------------------------------------------------------

def record_metric(memory: dict, tool_name: str, success: bool, error_type: Optional[str] = None):
    """Track basic per-tool success/error counts."""
    if "tool_metrics" not in memory:
        memory["tool_metrics"] = {}

    metrics = memory["tool_metrics"]
    if tool_name not in metrics:
        metrics[tool_name] = {"calls": 0, "errors": 0, "last_error": None}

    metrics[tool_name]["calls"] += 1
    if not success:
        metrics[tool_name]["errors"] += 1
        metrics[tool_name]["last_error"] = error_type
