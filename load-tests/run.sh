#!/usr/bin/env bash
# Convenience runner for the k6 load tests.
#
#   ./load-tests/run.sh chat 1000
#   ./load-tests/run.sh dashboard 5000
#
# Requires k6 (https://k6.io/docs/get-started/installation/).
set -euo pipefail

TEST="${1:-chat}"
PROFILE="${2:-smoke}"
RESULTS_DIR="$(dirname "$0")/results"
mkdir -p "$RESULTS_DIR"

case "$TEST" in
  chat)
    BASE_URL="${BASE_URL:-http://localhost:8001}"
    SCRIPT="$(dirname "$0")/k6/chat.js"
    ;;
  dashboard)
    BASE_URL="${BASE_URL:-http://localhost:8004}"
    SCRIPT="$(dirname "$0")/k6/dashboard.js"
    ;;
  *)
    echo "Unknown test '$TEST' (expected: chat|dashboard)" >&2
    exit 1
    ;;
esac

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$RESULTS_DIR/${TEST}-${PROFILE}-${STAMP}.json"

echo "▶ Running k6 '$TEST' profile=$PROFILE against $BASE_URL"
k6 run \
  -e PROFILE="$PROFILE" \
  -e BASE_URL="$BASE_URL" \
  -e STREAM="${STREAM:-false}" \
  --summary-export "$OUT" \
  "$SCRIPT"

echo "✔ Summary written to $OUT"
