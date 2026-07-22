#!/usr/bin/env bash
# metrics-service + Postgres down. It's read-only and has exactly one
# dependency (Postgres) - readiness must flip to 503 and dashboard queries
# must fail cleanly, not hang or crash the process.
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 40: metrics-service behavior when Postgres is down ==="
login

restore() { start_container postgres; wait_for_status "$METRICS_BASE/health/ready" 200 30 > /dev/null; }
trap 'restore' EXIT

info "stopping postgres"
stop_container postgres
sleep 2

ready_body=$(curl -s "$METRICS_BASE/health/ready")
if echo "$ready_body" | grep -q '"database":false'; then
  pass "metrics-service /health/ready reports database:false while postgres is down"
else
  fail "metrics-service /health/ready did not report database:false (body: $ready_body)"
fi

code=$(http_code -c "$JAR" -b "$JAR" "$METRICS_BASE/metrics/dashboard?window=24h")
if [ "$code" -ge 500 ]; then
  pass "GET /metrics/dashboard fails cleanly ($code) while postgres is down"
else
  fail "GET /metrics/dashboard returned $code while postgres is down (expected a 5xx)"
fi

liveness=$(http_code "$METRICS_BASE/health")
if [ "$liveness" = "200" ]; then
  pass "metrics-service liveness still 200 (process itself did not crash)"
else
  fail "metrics-service liveness -> $liveness"
fi

info "restarting postgres"
start_container postgres
if wait_for_status "$METRICS_BASE/health/ready" 200 30; then
  pass "metrics-service recovers (readiness -> 200) within 30s of postgres returning"
else
  fail "metrics-service did not recover within 30s"
fi

summary
