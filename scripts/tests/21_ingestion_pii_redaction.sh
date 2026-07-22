#!/usr/bin/env bash
# Sends a chat message containing PII-shaped content (email, card number,
# phone) and verifies app/ingestion-service/app/pii.py actually redacted it
# before persistence - by querying the real inference_logs.prompt_preview
# column directly (there's no public API for raw log content).
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 21: PII redaction actually redacts before persistence ==="
login
csrf=$(csrf)

MARKER="pii-test-$(date +%s)"
MSG="${MARKER} contact me at victim@example.com or call 555-123-4567, card 4111111111111111"

resp=$(curl -s -c "$JAR" -b "$JAR" -X POST "$CHAT_BASE/chat" -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -d "{\"message\":\"$MSG\",\"stream\":false}")
request_id=$(echo "$resp" | python3 -c "import json,sys; print(json.load(sys.stdin).get('request_id',''))" 2>/dev/null || echo "")

if [ -z "$request_id" ]; then
  fail "chat request itself failed - can't test the pipeline (resp: $resp)"
  summary; exit 1
fi

info "sent message with request_id=$request_id, waiting up to 20s for the Kafka pipeline to persist it"
found=""
row=""
for _ in $(seq 1 10); do
  row=$(docker exec llm-observability-postgres-1 psql -U postgres -d llm_observability -t -A \
    -c "SELECT prompt_preview FROM inference_logs WHERE request_id = '$request_id';" 2>/dev/null || echo "")
  if [ -n "$row" ]; then
    found="yes"
    break
  fi
  sleep 2
done

if [ -z "$found" ]; then
  fail "no inference_logs row appeared for request_id=$request_id within 20s - pipeline may be stalled"
  summary; exit 1
fi

info "persisted prompt_preview: $row"
ok=true
if echo "$row" | grep -q "victim@example.com"; then
  fail "raw email leaked into prompt_preview unredacted"
  ok=false
fi
if echo "$row" | grep -q "4111111111111111"; then
  fail "raw card number leaked into prompt_preview unredacted"
  ok=false
fi
if echo "$row" | grep -q "REDACTED_EMAIL"; then
  pass "email was redacted ([REDACTED_EMAIL] present)"
else
  fail "no [REDACTED_EMAIL] marker found - email redaction may not have applied"
  ok=false
fi
if echo "$row" | grep -q "REDACTED_CARD"; then
  pass "card number was redacted ([REDACTED_CARD] present)"
else
  fail "no [REDACTED_CARD] marker found - card redaction may not have applied"
  ok=false
fi
$ok && pass "no raw PII found in the persisted prompt_preview"

summary
