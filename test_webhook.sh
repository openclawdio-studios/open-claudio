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
BODY_FILE=$(mktemp)

# ---- Helpers -------------------------------------------------------

ok()   { echo "  ✅ $1"; PASSED=$((PASSED + 1)); }
fail() { echo "  ❌ $1: $2"; FAILED=$((FAILED + 1)); }
boom() { echo "  💥 $1: cannot connect to $BASE_URL — is the stack running?"; FAILED=$((FAILED + 1)); }
body() { cat "$BODY_FILE"; }

# GET request — returns HTTP status code, body written to $BODY_FILE
do_get() {
    curl -s -o "$BODY_FILE" -w "%{http_code}" --connect-timeout 5 "$1"
}

# POST request — uses bash array to avoid quoting issues with headers
# $1=url  $2=json_body  $3=Authorization header value (optional, e.g. "Bearer token")
do_post() {
    local url="$1" data="$2" auth="$3"
    local args=(-s -o "$BODY_FILE" -w "%{http_code}" --connect-timeout 5
                -X POST -H "Content-Type: application/json" -d "$data")
    [[ -n "$auth" ]] && args+=(-H "Authorization: $auth")
    curl "${args[@]}" "$url"
}

# ---- Tests ---------------------------------------------------------

test_health() {
    local name="GET /health → 200 ok"
    local status
    status=$(do_get "$BASE_URL/health") || { boom "$name"; return; }
    [[ "$status" != "200" ]] && { fail "$name" "Expected 200, got $status"; return; }
    body | grep -q '"status"' || { fail "$name" "Missing status in body: $(body)"; return; }
    ok "$name"
}

test_no_auth_rejected() {
    local name="POST /event (no auth) → 401"
    local status
    status=$(do_post "$BASE_URL/event" '{"payload":{"text":"test"}}') || { boom "$name"; return; }
    [[ "$status" != "401" ]] && { fail "$name" "Expected 401, got $status"; return; }
    ok "$name"
}

test_wrong_secret_rejected() {
    local name="POST /event (wrong secret) → 401"
    local status
    status=$(do_post "$BASE_URL/event" '{"payload":{"text":"test"}}' "Bearer wrong-token-xyz") || { boom "$name"; return; }
    [[ "$status" != "401" ]] && { fail "$name" "Expected 401, got $status"; return; }
    ok "$name"
}

test_command_queued() {
    local name="POST /event (command) → 200 queued"
    local data='{"event_type":"command","topic":"http/webhook","payload":{"text":"Dime la hora actual"}}'
    local status
    status=$(do_post "$BASE_URL/event" "$data" "Bearer $SECRET") || { boom "$name"; return; }
    [[ "$status" != "200" ]] && { fail "$name" "Expected 200, got $status — $(body)"; return; }
    body | grep -q '"queued"' || { fail "$name" "Expected queued in body: $(body)"; return; }
    ok "$name"
}

test_motion_event_queued() {
    local name="POST /event (motion_detected) → 200 queued"
    local data='{"event_type":"motion_detected","topic":"home/sensors/motion/sala","payload":{"detected":true,"room":"sala"}}'
    local status
    status=$(do_post "$BASE_URL/event" "$data" "Bearer $SECRET") || { boom "$name"; return; }
    [[ "$status" != "200" ]] && { fail "$name" "Expected 200, got $status — $(body)"; return; }
    ok "$name"
}

test_flood_alert_queued() {
    local name="POST /event (flood_detected) → 200 queued"
    local data='{"event_type":"flood_detected","topic":"home/sensors/flood/bathroom","payload":{"detected":true,"sensor_id":"flood_01"},"metadata":{"simulated":true}}'
    local status
    status=$(do_post "$BASE_URL/event" "$data" "Bearer $SECRET") || { boom "$name"; return; }
    [[ "$status" != "200" ]] && { fail "$name" "Expected 200, got $status — $(body)"; return; }
    ok "$name"
}

test_server_alert_queued() {
    local name="POST /event (disk_alert) → 200 queued"
    local data='{"event_type":"disk_alert","topic":"server/alert/disk","payload":{"usage_percent":95,"path":"/var/lib/docker"}}'
    local status
    status=$(do_post "$BASE_URL/event" "$data" "Bearer $SECRET") || { boom "$name"; return; }
    [[ "$status" != "200" ]] && { fail "$name" "Expected 200, got $status — $(body)"; return; }
    ok "$name"
}

test_missing_payload_rejected() {
    local name="POST /event (missing payload) → 422"
    local data='{"event_type":"command"}'
    local status
    status=$(do_post "$BASE_URL/event" "$data" "Bearer $SECRET") || { boom "$name"; return; }
    [[ "$status" != "422" ]] && { fail "$name" "Expected 422, got $status"; return; }
    ok "$name"
}

test_response_shape() {
    local name="POST /event response shape (status/topic/event_type present)"
    local data='{"event_type":"test_event","topic":"http/webhook","payload":{"text":"shape check"}}'
    local status
    status=$(do_post "$BASE_URL/event" "$data" "Bearer $SECRET") || { boom "$name"; return; }
    [[ "$status" != "200" ]] && { fail "$name" "Expected 200, got $status — $(body)"; return; }
    local resp; resp=$(body)
    echo "$resp" | grep -q '"status"'     || { fail "$name" "Missing 'status': $resp"; return; }
    echo "$resp" | grep -q '"topic"'      || { fail "$name" "Missing 'topic': $resp"; return; }
    echo "$resp" | grep -q '"event_type"' || { fail "$name" "Missing 'event_type': $resp"; return; }
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

rm -f "$BODY_FILE"

echo "=================================================="
echo "Results: $PASSED passed, $FAILED failed"
[[ $FAILED -gt 0 ]] && exit 1
echo "All tests passed! ✅"
