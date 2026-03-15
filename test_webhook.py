"""
Integration tests for the Open-Claudio HTTP Webhook endpoint.

Hits the real running server — start the stack before running:
    docker-compose up -d

Usage:
    python test_webhook.py                              # defaults
    python test_webhook.py --url http://localhost:8085  # custom URL
    python test_webhook.py --secret mysecret            # custom secret

Environment variables (override defaults):
    WEBHOOK_URL    — base URL of the agent HTTP API  (default: http://localhost:8085)
    HTTP_EVENT_SECRET — Bearer token                 (read from .env if not set)
"""

import argparse
import json
import os
import sys

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_secret_from_env_file(path=".env") -> str:
    """Parse HTTP_EVENT_SECRET from the .env file if not set in the environment."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("HTTP_EVENT_SECRET="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return ""


def parse_args():
    parser = argparse.ArgumentParser(description="Open-Claudio webhook integration tests")
    parser.add_argument("--url", default=os.getenv("WEBHOOK_URL", "http://localhost:8085"),
                        help="Base URL of the agent HTTP API")
    parser.add_argument("--secret", default=None,
                        help="Bearer token (reads from env/env-file if omitted)")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def auth_headers(secret: str) -> dict:
    return {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}


def post_event(base_url: str, secret: str, payload: dict) -> requests.Response:
    return requests.post(
        f"{base_url}/event",
        headers=auth_headers(secret),
        json=payload,
        timeout=5,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_health(base_url: str):
    """GET /health should return 200 and status ok."""
    r = requests.get(f"{base_url}/health", timeout=5)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    body = r.json()
    assert body.get("status") == "ok", f"Unexpected body: {body}"
    print("  GET /health → 200 ok")


def test_no_auth_rejected(base_url: str):
    """POST /event without Authorization header should return 401."""
    r = requests.post(
        f"{base_url}/event",
        json={"payload": {"text": "test"}},
        timeout=5,
    )
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"
    print("  POST /event (no auth) → 401 Unauthorized")


def test_wrong_secret_rejected(base_url: str):
    """POST /event with wrong token should return 401."""
    r = requests.post(
        f"{base_url}/event",
        headers={"Authorization": "Bearer wrong-token-xyz"},
        json={"payload": {"text": "test"}},
        timeout=5,
    )
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"
    print("  POST /event (wrong secret) → 401 Unauthorized")


def test_command_queued(base_url: str, secret: str):
    """A plain text command should be accepted and queued."""
    r = post_event(base_url, secret, {
        "event_type": "command",
        "topic": "http/webhook",
        "payload": {"text": "Dime la hora actual"},
    })
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("status") == "queued", f"Unexpected body: {body}"
    assert body.get("topic") == "http/webhook"
    print("  POST /event (command) → 200 queued")


def test_home_event_queued(base_url: str, secret: str):
    """A home sensor event should be accepted and queued."""
    r = post_event(base_url, secret, {
        "event_type": "motion_detected",
        "topic": "home/sensors/motion/sala",
        "payload": {"detected": True, "room": "sala"},
    })
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("status") == "queued"
    print("  POST /event (motion_detected) → 200 queued")


def test_flood_alert_queued(base_url: str, secret: str):
    """A flood sensor event should be accepted and queued."""
    r = post_event(base_url, secret, {
        "event_type": "flood_detected",
        "topic": "home/sensors/flood/bathroom",
        "payload": {"detected": True, "sensor_id": "flood_01"},
        "metadata": {"simulated": True},
    })
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("status") == "queued"
    print("  POST /event (flood_detected) → 200 queued")


def test_server_alert_queued(base_url: str, secret: str):
    """A server alert event should be accepted and queued."""
    r = post_event(base_url, secret, {
        "event_type": "disk_alert",
        "topic": "server/alert/disk",
        "payload": {"usage_percent": 95, "path": "/var/lib/docker"},
    })
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("status") == "queued"
    print("  POST /event (disk_alert) → 200 queued")


def test_missing_payload_rejected(base_url: str, secret: str):
    """Request without a payload field should return 422 (FastAPI validation)."""
    r = requests.post(
        f"{base_url}/event",
        headers=auth_headers(secret),
        json={"event_type": "command"},   # no payload key
        timeout=5,
    )
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    print("  POST /event (missing payload) → 422 Unprocessable Entity")


def test_response_shape(base_url: str, secret: str):
    """Response body should always contain status, topic, and event_type."""
    r = post_event(base_url, secret, {
        "event_type": "test_event",
        "topic": "http/webhook",
        "payload": {"text": "shape check"},
    })
    assert r.status_code == 200
    body = r.json()
    assert "status" in body,     f"Missing 'status' in response: {body}"
    assert "topic" in body,      f"Missing 'topic' in response: {body}"
    assert "event_type" in body, f"Missing 'event_type' in response: {body}"
    print("  POST /event (shape check) → status/topic/event_type present")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all(base_url: str, secret: str):
    tests_no_auth = [
        ("health endpoint",          lambda: test_health(base_url)),
        ("no auth → 401",            lambda: test_no_auth_rejected(base_url)),
        ("wrong secret → 401",       lambda: test_wrong_secret_rejected(base_url)),
    ]
    tests_with_auth = [
        ("plain command queued",     lambda: test_command_queued(base_url, secret)),
        ("home motion event queued", lambda: test_home_event_queued(base_url, secret)),
        ("flood alert queued",       lambda: test_flood_alert_queued(base_url, secret)),
        ("server alert queued",      lambda: test_server_alert_queued(base_url, secret)),
        ("missing payload → 422",    lambda: test_missing_payload_rejected(base_url, secret)),
        ("response shape check",     lambda: test_response_shape(base_url, secret)),
    ]

    passed = failed = 0

    print(f"\nOpen-Claudio Webhook Tests")
    print(f"Target: {base_url}")
    print("=" * 50)

    for name, fn in tests_no_auth + tests_with_auth:
        try:
            fn()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {name}: {e}")
            failed += 1
        except requests.exceptions.ConnectionError:
            print(f"  💥 {name}: cannot connect to {base_url} — is the stack running?")
            failed += 1
        except Exception as e:
            print(f"  💥 {name}: {e}")
            failed += 1

    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")

    if failed > 0:
        sys.exit(1)

    print("All tests passed! ✅")


if __name__ == "__main__":
    args = parse_args()
    secret = args.secret or os.getenv("HTTP_EVENT_SECRET") or _load_secret_from_env_file()

    if not secret:
        print("ERROR: HTTP_EVENT_SECRET not found.")
        print("Set it via --secret, the HTTP_EVENT_SECRET env var, or in your .env file.")
        sys.exit(1)

    run_all(base_url=args.url, secret=secret)
