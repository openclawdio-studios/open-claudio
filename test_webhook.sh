#!/usr/bin/env bash
# ============================================================
# Open-Claudio — Webhook integration tests (curl, no Python)
# Run from the project root with the stack already up:
#
#   bash test_webhook.sh
#   bash test_webhook.sh http://localhost:8085 mysecret
# ============================================================

BASE_URL="${1:-${WEBHOOK_URL:-http://localhost:8085}}"
SECRET="${2:-${HTTP_EVENT_SECRET}}"

# Auto-read secret from .env if not provided
if [[ -z "$SECRET" && -f ".env" ]]; then
    SECRET=$(grep -E '^HTTP_EVENT_SECRET=' .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
fi

if [[ -z "$SECRET" ]]; then
    echo "ERROR: HTTP_EVENT_SECRET not found."
    echo "Set it via: bash test_webhook.sh <url> <secret>"
    echo "Or set HTTP_EVENT_SECRET in your .env file."
    exit 1
fi

PASSED=0
FAILED=0

# ---- Helpers -------------------------------------------------------

ok()   { echo "  ✅ $1"; PASSED=$((PASSED + 1)); }
fail() { echo "  ❌ $1: $2"; FAILED=$((FAILED + 1)); }
boom() { echo "  💥 $1: cannot connect to $BASE_URL — is the stack running?"; FAILED=$((FAILED + 1)); }

# Returns HTTP status code; body goes to /tmp/wh_body.json
http_get() {
    curl -s -o /tmp/wh_body.json -w "%{http_code}" --connect-timeout 5 "$1"
}

http_post() {
    # $1 = extra headers string, $2 = url, $3 = json body
    curl -s -o /tmp/wh_body.json -w "%{http_code}" --connect-timeout 5 \
        -X POST -H "Content-Type: application/json" $1 -d "$3" "$2"
}

body() { cat /tmp/wh_body.json; }

# ---- Tests ---------------------------------------------------------

test_health() {
    local name="GET /health → 200 ok"
    local status
    status=$(http_get "$BASE_URL/health") || { boom "$name"; return; }
    if [[ "$status" != "200" ]]; then
        fail "$name" "Expected 200, got $status"; return
    fi
    local got_status
    got_status=$(body | grep -o '"status":"ok"')
    if [[ -z "$got_status" ]]; then
        fail "$name" "Body did not contain status:ok — $(body)"; return
    fi
    ok "$name"
}

test_no_auth_rejected() {
    local name="POST /event (no auth) → 401"
    local status
    status=$(http_post "" "$BASE_URL/event" '{"payload":{"text":"test"}}') || { boom "$name"; return; }
    if [[ "$status" != "401" ]]; then
        fail "$name" "Expected 401, got $status"; return
    fi
    ok "$name"
}

test_wrong_secret_rejected() {
    local name="POST /event (wrong secret) → 401"
    local status
    status=$(http_post '-H "Authorization: Bearer wrong-token-xyz"' "$BASE_URL/event" '{"payload":{"text":"test"}}') || { boom "$name"; return; }
    if [[ "$status" != "401" ]]; then
        fail "$name" "Expected 401, got $status"; return
    fi
    ok "$name"
}

test_command_queued() {
    local name="POST /event (command) → 200 queued"
    local body='{"event_type":"command","topic":"http/webhook","payload":{"text":"Dime la hora actual"}}'
    local status
    status=$(http_post "-H \"Authorization: Bearer $SECRET\"" "$BASE_URL/event" "$body") || { boom "$name"; return; }
    if [[ "$status" != "200" ]]; then
        fail "$name" "Expected 200, got $status — $(body)"; return
    fi
    if ! body | grep -q '"queued"'; then
        fail "$name" "Expected status:queued — $(body)"; return
    fi
    ok "$name"
}

test_motion_event_queued() {
    local name="POST /event (motion_detected) → 200 queued"
    local body='{"event_type":"motion_detected","topic":"home/sensors/motion/sala","payload":{"detected":true,"room":"sala"}}'
    local status
    status=$(http_post "-H \"Authorization: Bearer $SECRET\"" "$BASE_URL/event" "$body") || { boom "$name"; return; }
    if [[ "$status" != "200" ]]; then
        fail "$name" "Expected 200, got $status — $(body)"; return
    fi
    ok "$name"
}

test_flood_alert_queued() {
    local name="POST /event (flood_detected) → 200 queued"
    local body='{"event_type":"flood_detected","topic":"home/sensors/flood/bathroom","payload":{"detected":true,"sensor_id":"flood_01"},"metadata":{"simulated":true}}'
    local status
    status=$(http_post "-H \"Authorization: Bearer $SECRET\"" "$BASE_URL/event" "$body") || { boom "$name"; return; }
    if [[ "$status" != "200" ]]; then
        fail "$name" "Expected 200, got $status — $(body)"; return
    fi
    ok "$name"
}

test_server_alert_queued() {
    local name="POST /event (disk_alert) → 200 queued"
    local body='{"event_type":"disk_alert","topic":"server/alert/disk","payload":{"usage_percent":95,"path":"/var/lib/docker"}}'
    local status
    status=$(http_post "-H \"Authorization: Bearer $SECRET\"" "$BASE_URL/event" "$body") || { boom "$name"; return; }
    if [[ "$status" != "200" ]]; then
        fail "$name" "Expected 200, got $status — $(body)"; return
    fi
    ok "$name"
}

test_missing_payload_rejected() {
    local name="POST /event (missing payload) → 422"
    local body='{"event_type":"command"}'
    local status
    status=$(http_post "-H \"Authorization: Bearer $SECRET\"" "$BASE_URL/event" "$body") || { boom "$name"; return; }
    if [[ "$status" != "422" ]]; then
        fail "$name" "Expected 422, got $status"; return
    fi
    ok "$name"
}

test_response_shape() {
    local name="POST /event response shape (status/topic/event_type present)"
    local body='{"event_type":"test_event","topic":"http/webhook","payload":{"text":"shape check"}}'
    local status
    status=$(http_post "-H \"Authorization: Bearer $SECRET\"" "$BASE_URL/event" "$body") || { boom "$name"; return; }
    if [[ "$status" != "200" ]]; then
        fail "$name" "Expected 200, got $status"; return
    fi
    local resp
    resp=$(body)
    if ! echo "$resp" | grep -q '"status"'; then
        fail "$name" "Missing 'status' in response: $resp"; return
    fi
    if ! echo "$resp" | grep -q '"topic"'; then
        fail "$name" "Missing 'topic' in response: $resp"; return
    fi
    if ! echo "$resp" | grep -q '"event_type"'; then
        fail "$name" "Missing 'event_type' in response: $resp"; return
    fi
    ok "$name"
}

# ---- Main ----------------------------------------------------------

echo ""
echo "Open-Claudio Webhook Tests (curl)"
echo "Target: $BASE_URL"
echo "=================================================="

test_health
test_no_auth_rejected
test_wrong_secret_rejected
test_command_queued
test_motion_event_queued
test_flood_alert_queued
test_server_alert_queued
test_missing_payload_rejected
test_response_shape

echo "=================================================="
echo "Results: $PASSED passed, $FAILED failed"

if [[ $FAILED -gt 0 ]]; then
    exit 1
fi

echo "All tests passed! ✅"
