#!/usr/bin/env bash
# chat-service + SearXNG down. Per app/services/web_search.py, a search
# failure is caught and turned into a "Search failed: ..." tool result
# string, not an exception - the model still gets to answer. This forces a
# question that should trigger the web_search tool, with SearXNG stopped,
# and checks the request still completes rather than erroring out entirely.
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 14: chat-service behavior when SearXNG (web search tool) is down ==="
login
csrf=$(csrf)

restore() { start_container searxng; }
trap 'restore' EXIT

info "stopping searxng"
stop_container searxng
sleep 2

# Wording deliberately matches app/services/chat_service.py's system prompt
# guidance ("today", "latest", "current") so the model is likely to reach
# for the tool rather than answer from training data alone.
resp=$(curl -s -w "\n%{http_code}" -c "$JAR" -b "$JAR" -X POST "$CHAT_BASE/chat" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -d '{"message":"What are the latest headlines in the news today?","stream":false}')
body=$(echo "$resp" | sed '$d')
code=$(echo "$resp" | tail -1)

if [ "$code" = "200" ]; then
  pass "POST /chat still completes (200) with SearXNG down, even for a question likely to trigger web_search"
else
  fail "POST /chat returned $code with SearXNG down (expected 200 - a dead search tool should degrade gracefully, not fail the whole completion)"
fi

info "restarting searxng"
start_container searxng

summary
