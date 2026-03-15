"""
Tests for the self-healing tool layer (tool_healing.py).
Run with: python test_healing.py
No external dependencies needed — tests the pure logic only.
"""

import sys
import json

# Ensure we can import from the same directory
sys.path.insert(0, ".")
from tool_healing import (
    parse_tool_result, classify_error_string, get_strategy,
    build_repair_prompt, parse_llm_fix,
    lookup_known_fix, record_fix, record_metric,
    ToolResult,
)


def test_parse_structured_error():
    """Structured JSON error should be parsed correctly."""
    raw = json.dumps({
        "status": "error",
        "error_type": "validation_error",
        "message": "Unknown device 'livingroom'",
        "available_values": ["Ventana Salon", "Puerta Salon"]
    })
    result = parse_tool_result(raw)
    assert not result.success, "Should be an error"
    assert result.error_type == "validation_error"
    assert "livingroom" in result.content
    assert result.raw["available_values"] == ["Ventana Salon", "Puerta Salon"]
    print("✅ test_parse_structured_error")


def test_parse_structured_success():
    """JSON that is NOT an error should be treated as success."""
    raw = json.dumps({"name": "Test Device", "status": "online"})
    result = parse_tool_result(raw)
    assert result.success, "Should be success"
    print("✅ test_parse_structured_success")


def test_parse_plain_text_error():
    """Plain 'Error: ...' strings should be classified heuristically."""
    raw = "Error executing local tool xyz: connection refused"
    result = parse_tool_result(raw)
    assert not result.success, "Should be an error"
    assert result.error_type == "connection_error"
    print("✅ test_parse_plain_text_error")


def test_parse_plain_text_success():
    """Normal text without 'Error' prefix should be success."""
    raw = "OK: Persiana 'Ventana Salon' → acción 'on' ejecutada correctamente."
    result = parse_tool_result(raw)
    assert result.success, "Should be success"
    print("✅ test_parse_plain_text_success")


def test_classify_timeout():
    assert classify_error_string("API timed out after 10s") == "timeout"
    print("✅ test_classify_timeout")


def test_classify_permission():
    assert classify_error_string("Error: 401 Unauthorized") == "permission_error"
    print("✅ test_classify_permission")


def test_classify_unknown():
    assert classify_error_string("Error: something weird happened") == "unknown_error"
    print("✅ test_classify_unknown")


def test_strategies():
    """Each error type should map to the expected strategy."""
    assert get_strategy("connection_error") == "retry"
    assert get_strategy("timeout") == "retry"
    assert get_strategy("validation_error") == "llm_fix"
    assert get_strategy("permission_error") == "report"
    assert get_strategy("tool_not_found") == "report"
    assert get_strategy("unknown_error") == "retry_then_report"
    print("✅ test_strategies")


def test_build_repair_prompt():
    """Repair prompt should contain tool name, args, error, and available_values."""
    error = ToolResult(
        success=False, content="Unknown device 'livingroom'",
        error_type="validation_error",
        raw={"status": "error", "error_type": "validation_error",
             "message": "Unknown device 'livingroom'",
             "available_values": ["Ventana Salon", "Puerta Salon"]}
    )
    prompt = build_repair_prompt("set_blinds_state", {"room": "livingroom"}, error)
    assert "set_blinds_state" in prompt
    assert "livingroom" in prompt
    assert "Ventana Salon" in prompt
    assert "corrected JSON" in prompt
    print("✅ test_build_repair_prompt")


def test_parse_llm_fix_valid():
    """Should parse a valid JSON response from the LLM."""
    llm_response = '{"room": "Ventana Salon", "action": "on"}'
    result = parse_llm_fix(llm_response)
    assert result == {"room": "Ventana Salon", "action": "on"}
    print("✅ test_parse_llm_fix_valid")


def test_parse_llm_fix_with_fences():
    """Should strip markdown code fences."""
    llm_response = '```json\n{"room": "Ventana Salon"}\n```'
    result = parse_llm_fix(llm_response)
    assert result == {"room": "Ventana Salon"}
    print("✅ test_parse_llm_fix_with_fences")


def test_parse_llm_fix_invalid():
    """Should return None for non-JSON responses."""
    result = parse_llm_fix("I'm not sure what you mean")
    assert result is None
    print("✅ test_parse_llm_fix_invalid")


def test_lookup_known_fix():
    """Should find and apply a previously recorded fix."""
    memory = {
        "tool_fixes": [
            {
                "tool": "set_blinds_state",
                "original": {"room": "livingroom"},
                "fixed": {"room": "Ventana Salon"},
                "timestamp": "2026-01-01T00:00:00"
            }
        ]
    }
    # Should match
    result = lookup_known_fix(memory, "set_blinds_state", {"room": "livingroom", "action": "on"})
    assert result is not None
    assert result["room"] == "Ventana Salon"
    assert result["action"] == "on"  # preserved

    # Should NOT match different tool
    result2 = lookup_known_fix(memory, "other_tool", {"room": "livingroom"})
    assert result2 is None

    # Should NOT match different args
    result3 = lookup_known_fix(memory, "set_blinds_state", {"room": "salon"})
    assert result3 is None
    print("✅ test_lookup_known_fix")


def test_record_fix():
    """Should record a fix and avoid duplicates."""
    memory = {}
    record_fix(memory, "set_blinds_state", {"room": "livingroom"}, {"room": "Ventana Salon"})
    assert len(memory["tool_fixes"]) == 1
    assert memory["tool_fixes"][0]["original"] == {"room": "livingroom"}
    assert memory["tool_fixes"][0]["fixed"] == {"room": "Ventana Salon"}

    # Recording the same fix should update, not duplicate
    record_fix(memory, "set_blinds_state", {"room": "livingroom"}, {"room": "Puerta Salon"})
    assert len(memory["tool_fixes"]) == 1  # still 1
    assert memory["tool_fixes"][0]["fixed"] == {"room": "Puerta Salon"}  # updated
    print("✅ test_record_fix")


def test_record_metric():
    """Should track per-tool call counts and errors."""
    memory = {}
    record_metric(memory, "set_blinds_state", True)
    record_metric(memory, "set_blinds_state", True)
    record_metric(memory, "set_blinds_state", False, "timeout")

    metrics = memory["tool_metrics"]["set_blinds_state"]
    assert metrics["calls"] == 3
    assert metrics["errors"] == 1
    assert metrics["last_error"] == "timeout"
    print("✅ test_record_metric")


if __name__ == "__main__":
    tests = [
        test_parse_structured_error,
        test_parse_structured_success,
        test_parse_plain_text_error,
        test_parse_plain_text_success,
        test_classify_timeout,
        test_classify_permission,
        test_classify_unknown,
        test_strategies,
        test_build_repair_prompt,
        test_parse_llm_fix_valid,
        test_parse_llm_fix_with_fences,
        test_parse_llm_fix_invalid,
        test_lookup_known_fix,
        test_record_fix,
        test_record_metric,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"💥 {test.__name__}: {e}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed > 0:
        sys.exit(1)
    print("All tests passed! ✅")
