#!/usr/bin/env bash
# ingestion-service and consumer-service scale by Kafka consumer group
# semantics, not CPU alone reaching an arbitrary ceiling: a partition can
# only be actively consumed by one group member at a time, so scaling a
# consumer group beyond the topic's partition count leaves extra replicas
# permanently idle. infra/k8s/22-ingestion-service.yaml and
# 23-consumer-service.yaml cap maxReplicas at 3, matching the partition
# count infra/docker's kafka-init is *supposed* to create.
#
# This checks the ACTUAL running topic's partition count (not an assumed
# number) - because kafka-init uses `--create --if-not-exists`, which is a
# no-op for partition count on a topic that already exists in an older
# Kafka data volume, so a long-lived local environment can silently drift
# away from the documented/intended count.
set -uo pipefail
cd "$(dirname "$0")"
source ./lib.sh

echo "=== 61: ingestion/consumer scaling is correctly bounded by Kafka partition count ==="

EXPECTED_PARTITIONS=3  # per infra/docker's kafka-init and the HPAs' maxReplicas cap

partition_count() {
  docker exec llm-observability-kafka-1 /opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server localhost:9092 --describe --topic "$1" 2>/dev/null \
    | grep -c "	Partition: "
}

report_partitions() {
  local topic="$1" count="$2"
  if [ "$count" = "$EXPECTED_PARTITIONS" ]; then
    pass "$topic has $count partitions, matching the maxReplicas: $EXPECTED_PARTITIONS cap in the ingestion/consumer HPAs"
  else
    fail "$topic actually has $count partition(s), not the expected $EXPECTED_PARTITIONS. FINDING: kafka-init's --create --if-not-exists is a no-op on a topic that already exists in this Kafka data volume, so this local environment has silently drifted from the documented partition count. With only $count partition(s), only $count of the HPA's maxReplicas: $EXPECTED_PARTITIONS replicas could ever be active - the rest would sit permanently idle. Fix (destructive - deletes and recreates the topic, losing any unconsumed messages on it): 'docker exec llm-observability-kafka-1 /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --delete --topic $topic' then restart the kafka-init service."
  fi
}

actual_inference=$(partition_count "inference.logs")
actual_processed=$(partition_count "processed.logs")
report_partitions "inference.logs" "$actual_inference"
report_partitions "processed.logs" "$actual_processed"

check_group_owns_partitions() {
  local group="$1" topic="$2" expected="$3"
  local desc owned
  desc=$(docker exec llm-observability-kafka-1 /opt/kafka/bin/kafka-consumer-groups.sh \
    --bootstrap-server localhost:9092 --describe --group "$group" 2>/dev/null)
  # CONSUMER-ID is column 7: GROUP TOPIC PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG CONSUMER-ID HOST CLIENT-ID
  owned=$(echo "$desc" | awk -v t="$topic" '$2==t && $7 ~ /^[a-zA-Z0-9-]+-consumer-/' | wc -l | tr -d ' ')
  info "$group's single running instance actively owns $owned/$expected partition(s) of $topic"
  if [ "$owned" -ge 1 ]; then
    pass "$group is actively consuming at least one partition of $topic"
  else
    fail "$group does not appear to own any partition of $topic - consumer group may not be functioning. Raw output: $desc"
  fi
}

check_group_owns_partitions "ingestion-service" "inference.logs" "$actual_inference"
check_group_owns_partitions "consumer-service" "processed.logs" "$actual_processed"

summary
