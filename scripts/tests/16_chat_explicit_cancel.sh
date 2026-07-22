#!/usr/bin/env bash
# Formalizes the explicit-cancel fix: POST /chat/{request_id}/cancel must
# stop generation almost immediately, rather than relying on the backend
# inferring cancellation from a dropped connection (which used to let a
# fast provider generate nearly the entire response regardless of Stop).
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 16: explicit cancel endpoint stops generation near-immediately ==="
login
ACCESS=$(grep access_token "$JAR" | awk '{print $7}')
CSRF=$(csrf)

TMP_PY=$(mktemp -t explicit_cancel_test.XXXXXX.py)
TMP_OUT=$(mktemp -t explicit_cancel_out.XXXXXX)
cleanup() { rm -f "$TMP_PY" "$TMP_OUT"; }
trap cleanup EXIT

cat > "$TMP_PY" <<'PYEOF'
import http.client, json, sys, re, threading

csrf, access = sys.argv[1], sys.argv[2]
conn = http.client.HTTPConnection("localhost", 8001, timeout=20)
body = json.dumps({
    "message": "Write an extremely long, detailed 2000 word story about a desert caravan.",
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
request_id = None
cancel_result = {}
CUT_AFTER = 4000  # bytes of raw SSE, well before a ~2000-word response finishes

def fire_cancel(rid):
    # Mirrors useChat.ts's cancel(): call the cancel endpoint FIRST, then
    # (the caller) aborts its own connection - not the other way around,
    # since that ordering is what actually matters for latency.
    c2 = http.client.HTTPConnection("localhost", 8001, timeout=10)
    c2.request("POST", f"/chat/{rid}/cancel", body="{}", headers={
        "Content-Type": "application/json", "X-CSRF-Token": csrf,
        "Cookie": f"access_token={access}; csrf_token={csrf}",
    })
    r2 = c2.getresponse()
    cancel_result["code"] = r2.status
    r2.read()
    c2.close()

fired = False
while len(collected) < CUT_AFTER:
    chunk = resp.read(256)
    if not chunk:
        break
    collected += chunk
    if request_id is None:
        m = re.search(rb'"request_id": "([^"]+)"', collected)
        if m:
            request_id = m.group(1).decode()
        m2 = re.search(rb'"conversation_id": "([^"]+)"', collected)
        if m2:
            conv_id = m2.group(1).decode()
    if not fired and request_id:
        fired = True
        fire_cancel(request_id)   # synchronous - matches "cancel call completes, then abort"
        break

text = collected.decode(errors="ignore")
tokens = re.findall(r'event: token\r?\ndata: \{"content": "((?:[^"\\]|\\.)*)"\}', text)
tokens_text = "".join(t.encode().decode("unicode_escape") for t in tokens)
conn.close()

print(f"CONV_ID={conv_id or ''}")
print(f"REQUEST_ID={request_id or ''}")
print(f"CLIENT_SAW_CHARS={len(tokens_text)}")
print(f"CANCEL_HTTP_CODE={cancel_result.get('code', '')}")
PYEOF

python3 "$TMP_PY" "$CSRF" "$ACCESS" > "$TMP_OUT" 2>&1
CONV_ID=$(grep '^CONV_ID=' "$TMP_OUT" | cut -d= -f2-)
REQUEST_ID=$(grep '^REQUEST_ID=' "$TMP_OUT" | cut -d= -f2-)
CLIENT_SAW_CHARS=$(grep '^CLIENT_SAW_CHARS=' "$TMP_OUT" | cut -d= -f2-)
cancel_code=$(grep '^CANCEL_HTTP_CODE=' "$TMP_OUT" | cut -d= -f2-)

if [ -z "$REQUEST_ID" ]; then
  fail "could not capture a request_id - test setup failed"
  summary; exit 1
fi
info "client saw $CLIENT_SAW_CHARS chars, fired cancel immediately (mid-stream, before disconnecting)"

if [ "$cancel_code" = "200" ]; then
  pass "POST /chat/{request_id}/cancel -> 200"
else
  fail "POST /chat/{request_id}/cancel -> $cancel_code (expected 200)"
fi

sleep 2
body=$(curl -s -c "$JAR" -b "$JAR" "$CHAT_BASE/conversation/$CONV_ID")
persisted_chars=$(echo "$body" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    msgs = [m for m in d.get('messages', []) if m['role'] == 'assistant']
    print(len(msgs[-1]['content']) if msgs else -1)
except Exception:
    print(-1)
")

if [ "$persisted_chars" -lt 0 ]; then
  fail "no assistant message found after cancelling"
elif [ "$persisted_chars" -le $((CLIENT_SAW_CHARS + 200)) ]; then
  pass "persisted length ($persisted_chars chars) stayed close to what was cancelled at ($CLIENT_SAW_CHARS chars) - generation actually stopped"
else
  fail "persisted length ($persisted_chars chars) is far beyond what was streamed ($CLIENT_SAW_CHARS chars) - \
generation kept running well past the cancel call"
fi

summary
