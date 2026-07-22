#!/usr/bin/env bash
# chat-service + Postgres down: readiness must flip to 503, and a chat
# request must fail cleanly (5xx) rather than hang or crash the process.
# Restores postgres and confirms recovery before exiting either way.
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 10: chat-service behavior when Postgres is down ==="
login

restore() { start_container postgres; wait_for_status "$CHAT_BASE/health/ready" 200 30 > /dev/null; }
trap 'restore' EXIT

info "stopping postgres"
stop_container postgres
sleep 2

body=$(curl -s "$CHAT_BASE/health/ready")
if echo "$body" | grep -q '"database":false'; then
  pass "chat-service /health/ready reports database:false while postgres is down"
else
  fail "chat-service /health/ready did not report database:false (body: $body)"
fi

csrf=$(csrf)
code=$(curl -s -o /dev/null -w "%{http_code}" -c "$JAR" -b "$JAR" -X POST "$CHAT_BASE/chat" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -d '{"message":"hello while postgres is down","stream":false}')
if [ "$code" -ge 500 ] && [ "$code" -lt 600 ]; then
  pass "POST /chat fails cleanly with $code while postgres is down (not a hang/crash)"
else
  fail "POST /chat returned $code while postgres is down (expected a 5xx)"
fi

info "restarting postgres"
start_container postgres
if wait_for_status "$CHAT_BASE/health/ready" 200 30; then
  pass "chat-service recovers (readiness -> 200) within 30s of postgres returning"
else
  fail "chat-service did not recover within 30s of postgres returning"
fi

summary
