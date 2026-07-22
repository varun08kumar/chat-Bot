#!/usr/bin/env bash
# chat-service crash mid-stream. Verifies the fix built into
# ChatService.recover_or_run()/stream()'s Redis partial-buffer: if the
# worker is SIGKILL'd while streaming tokens to a client, whichever worker
# reclaims the orphaned job (via chat_worker.py's reclaim_orphaned) must
# persist EXACTLY what was already streamed - not silently regenerate a
# different answer, and not duplicate the message.
#
# Requires python3 (stdlib only - http.client). Kills and restarts the real
# chat-service container, so nothing else should be relying on it mid-test.
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 15: chat-service crash mid-stream -> honest partial recovery (not regeneration) ==="
login
ACCESS=$(grep access_token "$JAR" | awk '{print $7}')
CSRF=$(csrf)

TMP_PY=$(mktemp -t crash_recovery_test.XXXXXX.py)
TMP_OUT=$(mktemp -t crash_recovery_out.XXXXXX)
cleanup() { rm -f "$TMP_PY" "$TMP_OUT"; }
trap cleanup EXIT

cat > "$TMP_PY" <<'PYEOF'
import http.client, json, sys, re, subprocess, threading

csrf, access = sys.argv[1], sys.argv[2]
conn = http.client.HTTPConnection("localhost", 8001, timeout=30)
body = json.dumps({
    "message": "Write an extremely long, detailed 3000 word story about a train journey across a continent. Do not summarize.",
    "stream": True,
})
headers = {
    "Content-Type": "application/json", "Accept": "text/event-stream",
    "X-CSRF-Token": csrf, "Cookie": f"access_token={access}; csrf_token={csrf}",
}
conn.request("POST", "/chat", body=body, headers=headers)
resp = conn.getresponse()

collected = b""
conv_id = None
tokens_text = ""
killed = False
KILL_AFTER_CHARS = 80

try:
    while True:
        chunk = resp.read(32)
        if not chunk:
            break
        collected += chunk
        if conv_id is None:
            m = re.search(rb'"conversation_id": "([^"]+)"', collected)
            if m:
                conv_id = m.group(1).decode()
        text = collected.decode(errors="ignore")
        tokens = re.findall(r'event: token\r?\ndata: \{"content": "((?:[^"\\]|\\.)*)"\}', text)
        joined = "".join(t.encode().decode("unicode_escape") for t in tokens)
        if len(joined) > len(tokens_text):
            tokens_text = joined
        if not killed and len(tokens_text) >= KILL_AFTER_CHARS:
            killed = True
            threading.Thread(target=lambda: subprocess.run(
                ["docker", "kill", "llm-observability-chat-service-1"], capture_output=True
            )).start()
except Exception:
    pass

print(f"CONV_ID={conv_id or ''}")
print(f"CLIENT_SAW_CHARS={len(tokens_text)}")
print(f"CLIENT_SAW_TEXT={tokens_text}")
PYEOF

python3 "$TMP_PY" "$CSRF" "$ACCESS" > "$TMP_OUT" 2>&1
CONV_ID=$(grep '^CONV_ID=' "$TMP_OUT" | cut -d= -f2-)
CLIENT_SAW_CHARS=$(grep '^CLIENT_SAW_CHARS=' "$TMP_OUT" | cut -d= -f2-)
CLIENT_SAW_TEXT=$(grep '^CLIENT_SAW_TEXT=' "$TMP_OUT" | cut -d= -f2-)

if [ -z "$CONV_ID" ] || [ "${CLIENT_SAW_CHARS:-0}" -lt 40 ]; then
  fail "test setup itself failed (conv_id=$CONV_ID, chars=$CLIENT_SAW_CHARS) - can't validate recovery"
  summary; exit 1
fi
info "client saw $CLIENT_SAW_CHARS chars before the container was killed"

# Bring the container back (docker's restart policy may or may not fire in
# this environment; make sure it's actually up either way).
sleep 2
STATUS=$(docker inspect llm-observability-chat-service-1 --format '{{.State.Status}}' 2>/dev/null || echo "missing")
if [ "$STATUS" != "running" ]; then
  docker start llm-observability-chat-service-1 > /dev/null 2>&1
fi
wait_for "$CHAT_BASE/health" 30 > /dev/null
login  # session/cookies from before the crash are gone with the old process

# job_queue.py's XAUTOCLAIM only reclaims messages idle for at least
# chat_job_claim_idle_ms (30s default) - a deliberate guard against stealing
# a job from a merely-slow-but-alive worker. Poll rather than a fixed sleep,
# since the wait genuinely is that long by design.
info "waiting for the reclaim loop (idle threshold is 30s by design) - polling up to 50s"
found=""
for _ in $(seq 1 25); do
  body=$(curl -s -c "$JAR" -b "$JAR" "$CHAT_BASE/conversation/$CONV_ID" 2>/dev/null || echo "")
  if echo "$body" | grep -q '"role":"assistant"' || echo "$body" | grep -q '"role": "assistant"'; then
    found="yes"
    break
  fi
  sleep 2
done
if [ -z "$found" ]; then
  fail "no assistant message appeared within 50s of the crash - recovery did not happen in a reasonable time"
fi
# Note: conversation ownership ties to user_id, which is stable across
# logins for the same test account, so this should still be readable.
persisted=$(echo "$body" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    msgs = [m for m in d.get('messages', []) if m['role'] == 'assistant']
    print(msgs[-1]['content'] if msgs else '')
except Exception:
    print('')
")

if [ -z "$persisted" ]; then
  fail "no assistant message found in conversation $CONV_ID after crash - the response was lost entirely"
else
  info "persisted content: ${#persisted} chars"
  # The persisted text must START WITH what the client actually saw - i.e.
  # be an honest continuation, not a different regenerated answer.
  prefix="${persisted:0:$CLIENT_SAW_CHARS}"
  if [ "$prefix" = "$CLIENT_SAW_TEXT" ]; then
    pass "persisted content is an exact continuation of what the client saw (honest recovery, not regeneration)"
  else
    fail "persisted content does NOT match what the client saw - possible silent regeneration. \
client saw: ${CLIENT_SAW_TEXT:0:80}... | persisted starts with: ${persisted:0:80}..."
  fi
fi

# Exactly one assistant message - no duplicate from a blind re-run.
assistant_count=$(echo "$body" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(sum(1 for m in d.get('messages', []) if m['role'] == 'assistant'))
")
if [ "$assistant_count" = "1" ]; then
  pass "exactly one assistant message persisted (no duplicate from a second LLM call)"
else
  fail "found $assistant_count assistant messages (expected exactly 1)"
fi

summary
