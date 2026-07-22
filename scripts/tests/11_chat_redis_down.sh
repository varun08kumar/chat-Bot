#!/usr/bin/env bash
# chat-service + Redis down. Per app/services/cache.py, the rate limiter and
# conversation cache are designed to fail OPEN (Redis errors are caught,
# never raised). But Redis is also the transport for the Redis-Streams job
# queue that streaming responses depend on (job_queue.py) - that is NOT a
# "cache", so this documents what actually happens to a streaming request
# rather than assuming the whole service degrades gracefully.
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 11: chat-service behavior when Redis is down ==="
login

restore() { start_container redis; wait_for_status "$CHAT_BASE/health/ready" 200 30 > /dev/null; }
trap 'restore' EXIT

info "stopping redis"
stop_container redis
sleep 2

body=$(curl -s "$CHAT_BASE/health/ready")
if echo "$body" | grep -q '"redis":false'; then
  pass "chat-service /health/ready reports redis:false while redis is down"
else
  fail "chat-service /health/ready did not report redis:false (body: $body)"
fi

# Non-streaming path: prepare() only touches Postgres directly, and
# complete() calls the LLM directly (no Redis in that path at all) - this
# should still succeed, proving the "fail open" design for the non-streaming
# request/response path.
csrf=$(csrf)
code=$(curl -s -o /dev/null -w "%{http_code}" -c "$JAR" -b "$JAR" -X POST "$CHAT_BASE/chat" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -d '{"message":"say hi in 3 words","stream":false}')
if [ "$code" = "200" ]; then
  pass "non-streaming POST /chat still succeeds (200) with Redis down - rate limiter/cache fail open as designed"
else
  fail "non-streaming POST /chat returned $code with Redis down (expected 200 - fail-open broken)"
fi

# Streaming path: goes through the Redis Streams job queue (job_queue.py's
# enqueue -> XADD). This is core infra for streaming, not a cache. Checking
# HTTP status alone is misleading here: SSE sends a 200 status line as soon
# as the response starts, before anything in the body is known to succeed or
# fail - so what matters is whether the body ever actually produces bytes
# (an error event, at minimum) within a bounded time, or whether the
# connection just hangs.
bytes_received=$(curl -s -N --max-time 8 -c "$JAR" -b "$JAR" -X POST "$CHAT_BASE/chat" \
  -H "Content-Type: application/json" -H "Accept: text/event-stream" -H "X-CSRF-Token: $csrf" \
  -d '{"message":"say hi in 3 words","stream":true}' | wc -c | tr -d ' ')
if [ "$bytes_received" -gt 0 ]; then
  pass "streaming POST /chat produced $bytes_received bytes (some event, e.g. an error) within 8s of Redis being down"
else
  fail "streaming POST /chat produced ZERO bytes in 8s with Redis down - the connection HANGS rather than failing cleanly. \
Root cause: stream_via_queue()'s pubsub.subscribe()/job_queue.enqueue() calls have no explicit Redis connect/operation \
timeout, so an unreachable Redis blocks on the OS-level TCP timeout instead of raising quickly."
fi

info "restarting redis"
start_container redis
if wait_for_status "$CHAT_BASE/health/ready" 200 30; then
  pass "chat-service recovers (readiness -> 200) within 30s of redis returning"
else
  fail "chat-service did not recover within 30s of redis returning"
fi

summary
