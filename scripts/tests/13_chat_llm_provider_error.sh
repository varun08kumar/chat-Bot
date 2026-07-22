#!/usr/bin/env bash
# chat-service + LLM provider failure. Forces a real provider-level error
# (an invalid/nonexistent model id) rather than an infra outage, and checks
# it surfaces as a clean 502 (see routes_chat.py's `except LLMError`) instead
# of a 500/hang, and that the service is unaffected afterward.
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 13: chat-service behavior on an LLM provider error ==="
login
csrf=$(csrf)

resp=$(curl -s -w "\n%{http_code}" -c "$JAR" -b "$JAR" -X POST "$CHAT_BASE/chat" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -d '{"message":"hello","model":"groq/this-model-does-not-exist-at-all","stream":false}')
body=$(echo "$resp" | sed '$d')
code=$(echo "$resp" | tail -1)

if [ "$code" = "502" ]; then
  pass "POST /chat with an invalid model -> 502 (LLMError mapped cleanly, not a 500/crash)"
else
  fail "POST /chat with an invalid model -> $code (expected 502)"
fi

if echo "$body" | grep -qi "inference failed"; then
  pass "error body identifies it as an inference failure: $(echo "$body" | head -c 150)"
else
  fail "error body did not clearly identify the failure: $body"
fi

# The service itself must be unaffected - a provider error for one request
# must not degrade or crash the process for the next one.
code2=$(curl -s -o /dev/null -w "%{http_code}" -c "$JAR" -b "$JAR" -X POST "$CHAT_BASE/chat" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -d '{"message":"say hi in 3 words","stream":false}')
if [ "$code2" = "200" ]; then
  pass "a normal request immediately after the provider error still succeeds (200)"
else
  fail "a normal request after the provider error returned $code2 (expected 200 - service should be unaffected)"
fi

summary
