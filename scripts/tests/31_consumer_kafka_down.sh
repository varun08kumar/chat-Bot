#!/usr/bin/env bash
# consumer-service + Kafka down. Same shape as 20_ingestion_kafka_down.sh -
# checks it survives without crash-looping and recovers once Kafka returns.
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 31: consumer-service behavior when Kafka is down ==="

restore() { start_container kafka; }
trap 'restore' EXIT

info "stopping kafka"
stop_container kafka
sleep 5

liveness=$(http_code "http://localhost:8003/health")
if [ "$liveness" = "200" ]; then
  pass "consumer-service liveness still 200 with Kafka down - did not crash"
else
  fail "consumer-service liveness -> $liveness with Kafka down"
fi

info "restarting kafka"
start_container kafka
sleep 8
liveness2=$(http_code "http://localhost:8003/health")
ready2=$(http_code "http://localhost:8003/health/ready")
if [ "$liveness2" = "200" ]; then
  pass "consumer-service still healthy after Kafka returns"
else
  fail "consumer-service unhealthy after Kafka returned ($liveness2)"
fi
info "readiness after recovery: $ready2"

summary
