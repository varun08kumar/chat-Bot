#!/usr/bin/env bash
# chat-service + Kafka down. Per packages/sdk/producer.py's design goals,
# the SDK's KafkaLogProducer must never block inference: emit() only
# enqueues in-memory, a background worker drains to Kafka with retries, and
# on overflow the oldest event is dropped. This proves that design claim by
# actually completing chat requests while Kafka is unreachable.
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 12: chat-service behavior when Kafka is down (SDK must never block on it) ==="
login

restore() { start_container kafka; wait_for_status "$CHAT_BASE/health" 200 60 > /dev/null; }
trap 'restore' EXIT

info "stopping kafka"
stop_container kafka
sleep 2

csrf=$(csrf)
started=$(date +%s)
resp=$(curl -s -w "\n%{http_code}" -c "$JAR" -b "$JAR" -X POST "$CHAT_BASE/chat" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -d '{"message":"say hi in 3 words","stream":false}')
elapsed=$(( $(date +%s) - started ))
code=$(echo "$resp" | tail -1)

if [ "$code" = "200" ]; then
  pass "POST /chat still completes (200) with Kafka down - inference is never blocked on logging"
else
  fail "POST /chat returned $code with Kafka down (expected 200 - the SDK's fire-and-forget design should not fail the request)"
fi

if [ "$elapsed" -le 5 ]; then
  pass "request completed in ${elapsed}s - not waiting on the dead Kafka broker"
else
  fail "request took ${elapsed}s - suspiciously slow for a design that's supposed to never block on Kafka"
fi

info "restarting kafka"
start_container kafka
if wait_for_status "$CHAT_BASE/health" 200 60; then
  pass "chat-service still healthy after kafka returns"
else
  fail "chat-service unhealthy after kafka returns"
fi

summary
