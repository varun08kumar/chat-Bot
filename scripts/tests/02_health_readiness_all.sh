#!/usr/bin/env bash
# GET /health/ready must report each service's *actual* declared dependencies
# (see apps/*/app/main.py's install_observability(readiness_checks=...) calls)
# and nothing more - e.g. ingestion-service has no Postgres dependency, so it
# must not check one.
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 02: readiness (/health/ready) reports the right dependencies per service ==="

check_ready() {
  local name="$1" url="$2" expected_keys="$3"
  local body code
  body=$(curl -s "$url")
  code=$(curl -s -o /dev/null -w "%{http_code}" "$url")
  if [ "$code" != "200" ]; then
    fail "$name /health/ready -> $code (expected 200, all deps healthy)"
    return
  fi
  local ok=true
  for key in $expected_keys; do
    if ! echo "$body" | grep -q "\"$key\""; then
      fail "$name /health/ready missing expected check '$key' (body: $body)"
      ok=false
    fi
  done
  $ok && pass "$name /health/ready -> 200, checks=[$expected_keys]"
}

check_ready "chat-service"      "http://localhost:8001/health/ready" "database redis"
check_ready "ingestion-service" "http://localhost:8002/health/ready" "consumer"
check_ready "consumer-service"  "http://localhost:8003/health/ready" "database consumer"
check_ready "metrics-service"   "http://localhost:8004/health/ready" "database"

summary
