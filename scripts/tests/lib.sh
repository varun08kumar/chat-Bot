#!/usr/bin/env bash
# Shared helpers for scripts/tests/*.sh. Source this, don't run it directly:
#   source "$(dirname "$0")/lib.sh"
#
# Every test script is standalone and idempotent: it restores whatever
# container/state it touched before exiting, whether it passes or fails,
# so scripts can run individually or back-to-back via run_all.sh.

set -uo pipefail

COMPOSE="docker compose -f $(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/infra/docker/docker-compose.yml --env-file $(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/.env"
CHAT_BASE="http://localhost:8001"
METRICS_BASE="http://localhost:8004"
FRONTEND_BASE="http://localhost:3000"
JAR="$(mktemp -t llmobs-test-cookies.XXXXXX)"

_PASS=0
_FAIL=0

pass() { _PASS=$((_PASS+1)); echo "  PASS: $1"; }
fail() { _FAIL=$((_FAIL+1)); echo "  FAIL: $1"; }
info() { echo "  ... $1"; }

summary() {
  echo
  echo "== $_PASS passed, $_FAIL failed =="
  [ "$_FAIL" -eq 0 ]
}

cleanup_jar() { rm -f "$JAR"; }
trap cleanup_jar EXIT

# Logs in as the fixed test account, creating it on first use. Safe to call
# repeatedly (access tokens are only 3 minutes, most scripts re-login).
TEST_EMAIL="scripts-tests@example.com"
TEST_PASSWORD="ScriptsTests123!"

login() {
  rm -f "$JAR"
  local resp
  resp=$(curl -s -c "$JAR" -b "$JAR" -X POST "$CHAT_BASE/auth/register" -H "Content-Type: application/json" \
    -d "{\"email\":\"$TEST_EMAIL\",\"password\":\"$TEST_PASSWORD\"}")
  if ! echo "$resp" | grep -q '"id"'; then
    curl -s -c "$JAR" -b "$JAR" -X POST "$CHAT_BASE/auth/login" -H "Content-Type: application/json" \
      -d "{\"email\":\"$TEST_EMAIL\",\"password\":\"$TEST_PASSWORD\"}" > /dev/null
  fi
}

csrf() { grep csrf_token "$JAR" | awk '{print $7}'; }

# wait_for <url> <timeout_s> — polls a URL until it returns HTTP 200.
wait_for() {
  local url="$1" timeout="${2:-30}" waited=0
  while [ "$waited" -lt "$timeout" ]; do
    if curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null | grep -q "^200$"; then
      return 0
    fi
    sleep 1
    waited=$((waited+1))
  done
  return 1
}

# wait_for_status <url> <expected_code> <timeout_s>
wait_for_status() {
  local url="$1" expected="$2" timeout="${3:-30}" waited=0
  while [ "$waited" -lt "$timeout" ]; do
    if [ "$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null)" = "$expected" ]; then
      return 0
    fi
    sleep 1
    waited=$((waited+1))
  done
  return 1
}

stop_container() { $COMPOSE stop "$1" > /dev/null 2>&1; }
start_container() { $COMPOSE start "$1" > /dev/null 2>&1; }
restart_container() { $COMPOSE restart "$1" > /dev/null 2>&1; }
kill_container() { docker kill "llm-observability-$1-1" > /dev/null 2>&1; }

http_code() {
  curl -s -o /dev/null -w "%{http_code}" "$@"
}
