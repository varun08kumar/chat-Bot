#!/usr/bin/env bash
# Runs every test script in this directory in order and prints a summary.
# Scripts 00-50 assume the docker-compose stack (infra/docker) is already up
# (see scripts/dev_up.py) and take a few minutes total, mostly waiting out
# real container restarts. Script 60 (HPA) is much slower (several minutes:
# spins up its own kind cluster) and requires kind/kubectl/k6/docker - pass
# --skip-slow to omit it. Script 61 only needs the compose stack.
#
# Usage:
#   ./run_all.sh              # everything
#   ./run_all.sh --skip-slow  # everything except 60_scaling_hpa.sh
#   ./run_all.sh 10 11 16     # only the named scripts (numeric prefix or full name)
set -uo pipefail
cd "$(dirname "$0")"

SKIP_SLOW=false
ARGS=()
for a in "$@"; do
  if [ "$a" = "--skip-slow" ]; then SKIP_SLOW=true; else ARGS+=("$a"); fi
done

SCRIPTS=$(ls [0-9]*.sh 2>/dev/null | sort)
if [ "${#ARGS[@]}" -gt 0 ]; then
  FILTERED=""
  for s in $SCRIPTS; do
    for a in "${ARGS[@]}"; do
      [[ "$s" == "$a"* ]] && FILTERED="$FILTERED $s"
    done
  done
  SCRIPTS="$FILTERED"
fi

total_pass=0
total_fail=0
declare -a RESULTS

for script in $SCRIPTS; do
  if $SKIP_SLOW && [[ "$script" == 60_* ]]; then
    echo ">>> skipping $script (--skip-slow)"
    continue
  fi
  echo
  echo "############################################################"
  echo "# $script"
  echo "############################################################"
  if bash "./$script"; then
    RESULTS+=("PASS  $script")
  else
    RESULTS+=("FAIL  $script")
  fi
done

echo
echo "============================================================"
echo "SUMMARY"
echo "============================================================"
for r in "${RESULTS[@]}"; do
  echo "$r"
done

fail_count=$(printf '%s\n' "${RESULTS[@]}" | grep -c "^FAIL" || true)
echo
echo "${#RESULTS[@]} scripts run, $fail_count with at least one failing check."
[ "$fail_count" -eq 0 ]
