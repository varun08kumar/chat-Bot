#!/usr/bin/env bash
# Publishes a genuinely malformed message directly onto inference.logs
# (bypassing the SDK entirely) and verifies EventProcessor.process() rejects
# it (InvalidEventError) and IngestionConsumer routes it to the dead-letter
# topic instead of stalling the partition or crashing - see
# apps/ingestion-service/app/consumer.py's _handle().
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 22: a malformed Kafka message is dead-lettered, not lost or fatal ==="

MARKER="malformed-test-$(date +%s)"
BAD_JSON="{not valid json at all - $MARKER"

info "publishing malformed message directly to inference.logs"
echo "$BAD_JSON" | docker exec -i llm-observability-kafka-1 /opt/kafka/bin/kafka-console-producer.sh \
  --bootstrap-server localhost:9092 --topic inference.logs > /dev/null 2>&1

# A generous window: right after a Kafka outage elsewhere, aiokafka's
# consumer group can take a while to rebalance/reconnect, independent of
# this feature actually working.
info "waiting up to 60s for it to be consumed and routed to dead-letter"
found=""
for _ in $(seq 1 6); do
  out=$(docker exec llm-observability-kafka-1 /opt/kafka/bin/kafka-console-consumer.sh \
    --bootstrap-server localhost:9092 --topic dead-letter --from-beginning --timeout-ms 8000 2>/dev/null || echo "")
  if echo "$out" | grep -q "$MARKER"; then
    found="yes"
    break
  fi
  sleep 2
done

if [ -n "$found" ]; then
  pass "malformed message appeared on the dead-letter topic (not silently dropped)"
else
  fail "malformed message never appeared on dead-letter within 15s"
fi

# ingestion-service itself must still be healthy - one poison message must
# not crash the consumer or stall the partition for subsequent messages.
liveness=$(http_code "http://localhost:8002/health")
if [ "$liveness" = "200" ]; then
  pass "ingestion-service still healthy after processing the malformed message"
else
  fail "ingestion-service unhealthy after the malformed message ($liveness)"
fi

# Prove the partition isn't stalled: a normal chat message sent afterward
# must still make it all the way through to Postgres.
login
csrf=$(csrf)
MSG="post-poison-message-$(date +%s)"
resp=$(curl -s -c "$JAR" -b "$JAR" -X POST "$CHAT_BASE/chat" -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -d "{\"message\":\"$MSG\",\"stream\":false}")
request_id=$(echo "$resp" | python3 -c "import json,sys; print(json.load(sys.stdin).get('request_id',''))" 2>/dev/null || echo "")
recovered=""
if [ -n "$request_id" ]; then
  for _ in $(seq 1 10); do
    row=$(docker exec llm-observability-postgres-1 psql -U postgres -d llm_observability -t -A \
      -c "SELECT 1 FROM inference_logs WHERE request_id = '$request_id';" 2>/dev/null || echo "")
    [ -n "$row" ] && { recovered="yes"; break; }
    sleep 2
  done
fi
if [ -n "$recovered" ]; then
  pass "a normal message sent after the poison message still reaches Postgres (partition not stalled)"
else
  fail "a normal message after the poison message never reached Postgres - partition may be stalled"
fi

summary
