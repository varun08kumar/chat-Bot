#!/usr/bin/env bash
# frontend + chat-service down. The frontend has no direct infra
# dependencies of its own (it's a static SPA behind nginx) - its only
# "dependency" is chat-service being reachable through the /api proxy. This
# checks nginx/the SPA shell still serves (no crash) and that the API proxy
# path fails cleanly rather than hanging.
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 50: frontend behavior when chat-service (its backend) is down ==="

restore() { $COMPOSE start chat-service > /dev/null 2>&1; wait_for_status "$CHAT_BASE/health" 200 30 > /dev/null; }
trap 'restore' EXIT

info "stopping chat-service"
stop_container chat-service
sleep 2

code=$(http_code "$FRONTEND_BASE/")
if [ "$code" = "200" ]; then
  pass "frontend SPA shell (nginx) still serves 200 with chat-service down"
else
  fail "frontend / -> $code with chat-service down (expected 200 - the static shell shouldn't depend on the backend)"
fi

# The nginx-proxied API path should fail cleanly (502/503/504 from nginx
# not being able to reach chat-service), within a bounded time - not hang.
api_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$FRONTEND_BASE/api/providers")
if [ "$api_code" -ge 500 ] && [ "$api_code" -lt 600 ]; then
  pass "GET /api/providers (proxied to chat-service) fails cleanly ($api_code) within 10s"
else
  fail "GET /api/providers -> $api_code (expected a 5xx from nginx failing to reach chat-service)"
fi

info "restarting chat-service"
$COMPOSE start chat-service > /dev/null 2>&1
if wait_for_status "$CHAT_BASE/health" 200 30; then
  pass "chat-service recovers, and the frontend's API proxy should now work again"
  api_code2=$(http_code "$FRONTEND_BASE/api/providers")
  if [ "$api_code2" = "200" ]; then
    pass "GET /api/providers -> 200 again after chat-service recovers"
  else
    fail "GET /api/providers -> $api_code2 after chat-service recovered (expected 200)"
  fi
else
  fail "chat-service did not recover within 30s"
fi

summary
