#!/usr/bin/env bash
# Complements 11_chat_redis_down.sh's fail-open check: proves the fixed-
# window rate limiter (RateLimiter in app/services/cache.py, default 60
# requests / 60s per user) actually enforces a 429 when Redis is healthy,
# not just that it degrades gracefully when Redis is down.
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 18: rate limiter enforces its configured limit when Redis is healthy ==="

SUFFIX=$(date +%s)
EMAIL="rate-limit-test-${SUFFIX}@example.com"
curl -s -c "$JAR" -b "$JAR" -X POST "$CHAT_BASE/auth/register" -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"RateLimitTest123!\"}" > /dev/null
csrf=$(csrf)

# Default limit is 60 req/60s (app/config.py's rate_limit_requests). Use the
# cheap /chat/dummy route (10ms sleep, no LLM/DB/Kafka) so this is fast and
# isolates the rate limiter itself, not provider/DB latency.
info "firing 65 rapid requests against /chat/dummy (limit is 60/60s)"
got_429=false
last_code=""
for i in $(seq 1 65); do
  code=$(curl -s -o /dev/null -w "%{http_code}" -c "$JAR" -b "$JAR" -X POST "$CHAT_BASE/chat/dummy" \
    -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" -d '{"message":"hi","stream":false}')
  last_code="$code"
  if [ "$code" = "429" ]; then
    got_429=true
    info "got 429 on request #$i"
    break
  fi
done

# /chat/dummy has no @Depends rate limiter wired in routes_chat.py (it's the
# load-test isolation route) - only /chat itself enforces it. Re-check
# against the real /chat route if dummy never triggers it, so this test
# reflects what's actually wired up rather than assuming.
if ! $got_429; then
  info "/chat/dummy never hit 429 (expected - it has no rate-limit dependency); retrying against /chat"
  for i in $(seq 1 65); do
    code=$(curl -s -o /dev/null -w "%{http_code}" -c "$JAR" -b "$JAR" -X POST "$CHAT_BASE/chat" \
      -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" -d '{"message":"hi","stream":false}')
    last_code="$code"
    if [ "$code" = "429" ]; then
      got_429=true
      info "got 429 on request #$i against /chat"
      break
    fi
  done
fi

if $got_429; then
  pass "rate limiter returns 429 once the configured limit is exceeded"
else
  fail "never got a 429 after 65 rapid requests (last code: $last_code) - rate limiter may not be enforcing"
fi

summary
