#!/usr/bin/env bash
# Every service must answer GET /health (liveness: "the process is up"),
# regardless of whether its dependencies are reachable. See
# packages/shared/llm_obs_shared/fastapi_obs.py.
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 01: liveness (/health) on every backend service ==="

declare -A SERVICES=(
  [chat-service]="http://localhost:8001/health"
  [ingestion-service]="http://localhost:8002/health"
  [consumer-service]="http://localhost:8003/health"
  [metrics-service]="http://localhost:8004/health"
)

for name in "${!SERVICES[@]}"; do
  url="${SERVICES[$name]}"
  code=$(http_code "$url")
  if [ "$code" = "200" ]; then
    pass "$name /health -> 200"
  else
    fail "$name /health -> $code (expected 200)"
  fi
done

# Frontend is a static SPA behind nginx, not a FastAPI service - liveness
# here just means "nginx is serving the app shell".
code=$(http_code "$FRONTEND_BASE/")
if [ "$code" = "200" ]; then
  pass "frontend / -> 200"
else
  fail "frontend / -> $code (expected 200)"
fi

summary
