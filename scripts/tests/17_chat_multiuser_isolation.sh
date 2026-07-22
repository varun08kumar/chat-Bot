#!/usr/bin/env bash
# Formalizes this session's 3-account isolation test: concurrent requests
# from different accounts must never leak into each other's conversation
# lists, and one account must not be able to fetch another's conversation
# by id (ConversationRepository.get() filters by user_id).
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 17: multi-user isolation under concurrent use ==="

SUFFIX=$(date +%s)
declare -a JARS
for i in 1 2 3; do
  jar=$(mktemp -t isolation_jar_$i.XXXXXX)
  JARS[$i]="$jar"
  email="isolation-test-${SUFFIX}-${i}@example.com"
  curl -s -c "$jar" -b "$jar" -X POST "$CHAT_BASE/auth/register" -H "Content-Type: application/json" \
    -d "{\"email\":\"$email\",\"password\":\"IsolationTest123!\"}" > /dev/null
done
cleanup() { for i in 1 2 3; do rm -f "${JARS[$i]}"; done; }
trap cleanup EXIT

# Fire concurrent requests with distinct, easily-checked content per user.
declare -a RESP
for i in 1 2 3; do
  jar="${JARS[$i]}"
  csrf=$(grep csrf_token "$jar" | awk '{print $7}')
  ( curl -s -c "$jar" -b "$jar" -X POST "$CHAT_BASE/chat" -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
      -d "{\"message\":\"isolation-marker-user${i}-${SUFFIX}\",\"stream\":false}" \
      > "/tmp/isolation_resp_${i}_${SUFFIX}.json" ) &
done
wait

# Each user's own list must contain exactly their own marker and nobody else's.
ok=true
for i in 1 2 3; do
  jar="${JARS[$i]}"
  list=$(curl -s -c "$jar" -b "$jar" "$CHAT_BASE/conversations")
  count_own=$(echo "$list" | grep -o "isolation-marker-user${i}-${SUFFIX}" | wc -l | tr -d ' ')
  count_others=0
  for j in 1 2 3; do
    [ "$j" = "$i" ] && continue
    n=$(echo "$list" | grep -o "isolation-marker-user${j}-${SUFFIX}" | wc -l | tr -d ' ')
    count_others=$((count_others + n))
  done
  if [ "$count_own" -ge 1 ] && [ "$count_others" -eq 0 ]; then
    pass "user $i sees only their own marker (own=$count_own, others=$count_others)"
  else
    fail "user $i isolation broken (own=$count_own, others=$count_others)"
    ok=false
  fi
done

# Cross-account direct fetch by id must 404, not leak the data.
conv1=$(python3 -c "import json; print(json.load(open('/tmp/isolation_resp_1_${SUFFIX}.json'))['conversation_id'])" 2>/dev/null || echo "")
if [ -n "$conv1" ]; then
  jar2="${JARS[2]}"
  code=$(curl -s -o /dev/null -w "%{http_code}" -c "$jar2" -b "$jar2" "$CHAT_BASE/conversation/$conv1")
  if [ "$code" = "404" ]; then
    pass "user 2 fetching user 1's conversation by id -> 404 (not a leak)"
  else
    fail "user 2 fetching user 1's conversation by id -> $code (expected 404)"
  fi
else
  fail "could not determine user 1's conversation_id - test setup issue"
fi

rm -f /tmp/isolation_resp_*_${SUFFIX}.json
summary
