#!/usr/bin/env bash
# ingestion-service + Kafka down. IngestionConsumer.run()'s while loop
# catches nothing around consumer.getmany()/commit() itself (see
# consumer.py) - only the outer app lifespan does. This checks whether the
# service crash-loops or survives, and whether /health/ready's "consumer"
# check (which only reflects a `running` flag, not live Kafka connectivity -
# see main.py's _worker_ready) actually reflects the outage.
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 20: ingestion-service behavior when Kafka is down ==="

restore() { start_container kafka; }
trap 'restore' EXIT

info "stopping kafka"
stop_container kafka
sleep 5

liveness=$(http_code "http://localhost:8002/health")
if [ "$liveness" = "200" ]; then
  pass "ingestion-service liveness (/health) still 200 with Kafka down - process did not crash"
else
  fail "ingestion-service liveness -> $liveness with Kafka down (process may have crashed)"
fi

ready_body=$(curl -s "http://localhost:8002/health/ready")
ready_code=$(http_code "http://localhost:8002/health/ready")
info "readiness body with Kafka down: $ready_body (http $ready_code)"
if [ "$ready_code" = "200" ]; then
  info "FINDING: /health/ready still reports 200/ready with Kafka down - the 'consumer' check (main.py's _worker_ready) only reflects a 'running' flag set once at startup, not live Kafka connectivity, so this readiness probe cannot actually detect a Kafka outage."
fi

info "restarting kafka, checking the service recovers on its own (no restart needed)"
start_container kafka
sleep 5
liveness2=$(http_code "http://localhost:8002/health")
if [ "$liveness2" = "200" ]; then
  pass "ingestion-service still healthy after Kafka returns (survived the outage without crash-looping)"
else
  fail "ingestion-service unhealthy after Kafka returned"
fi

summary
