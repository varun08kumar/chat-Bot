#!/usr/bin/env bash
# Publishes the exact same ProcessedLogEvent twice directly onto
# processed.logs (simulating Kafka's at-least-once redelivery after a
# consumer crash/rebalance) and verifies InferenceLogRepository.insert_batch's
# ON CONFLICT DO NOTHING (keyed on request_id) results in exactly one row,
# not two.
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 32: replaying the same processed.logs event twice is idempotent ==="

REQUEST_ID=$(python3 -c "import uuid; print(uuid.uuid4().hex)")
NOW=$(python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())")
EVENT=$(python3 -c "
import json
print(json.dumps({
    'request_id': '$REQUEST_ID', 'correlation_id': None, 'session_id': None,
    'conversation_id': None, 'user_id': None,
    'provider': 'idempotency-test', 'model': 'idempotency-test-model', 'endpoint': '/chat',
    'prompt_preview': 'idempotent replay test', 'response_preview': 'ok',
    'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2,
    'latency_ms': 1.0, 'status': 'success', 'error': None, 'metadata': {},
    'timestamp': '$NOW', 'ingested_at': '$NOW', 'pii_redacted': False,
}))
")

info "publishing the same event twice (same request_id=$REQUEST_ID)"
for _ in 1 2; do
  echo "$EVENT" | docker exec -i llm-observability-kafka-1 /opt/kafka/bin/kafka-console-producer.sh \
    --bootstrap-server localhost:9092 --topic processed.logs > /dev/null 2>&1
  sleep 1
done

info "waiting up to 20s for both to be consumed"
count=""
for _ in $(seq 1 10); do
  count=$(docker exec llm-observability-postgres-1 psql -U postgres -d llm_observability -t -A \
    -c "SELECT COUNT(*) FROM inference_logs WHERE request_id = '$REQUEST_ID';" 2>/dev/null || echo "")
  [ "$count" = "1" ] && break
  sleep 2
done

if [ "$count" = "1" ]; then
  pass "exactly 1 row for request_id=$REQUEST_ID after publishing the same event twice (idempotent insert works)"
elif [ "$count" = "0" ] || [ -z "$count" ]; then
  fail "0 rows found - the event was never persisted at all (pipeline issue, not an idempotency issue)"
else
  fail "found $count rows for the same request_id (expected 1) - idempotent insert is NOT preventing duplicates"
fi

summary
