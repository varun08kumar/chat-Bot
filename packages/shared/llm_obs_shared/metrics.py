"""Prometheus metric definitions shared across services.

Metric *names* are standardised here so a single Grafana dashboard query works
against every service. Each metric is created with a custom registry-free
default registry (the global one) which ``prometheus_client`` exposes via
``generate_latest``.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

# Buckets tuned for sub-request HTTP latencies (seconds).
_HTTP_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
# Buckets tuned for LLM / Kafka / DB latencies (milliseconds).
_MS_BUCKETS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000)

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ["method", "path", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "path"],
    buckets=_HTTP_BUCKETS,
)

LLM_REQUESTS_TOTAL = Counter(
    "llm_requests_total",
    "Total LLM inference calls.",
    ["provider", "model", "status"],
)
LLM_LATENCY_MS = Histogram(
    "llm_latency_ms",
    "LLM inference latency in milliseconds.",
    ["provider", "model"],
    buckets=_MS_BUCKETS,
)
LLM_ERRORS_TOTAL = Counter(
    "llm_errors_total",
    "Total LLM inference errors.",
    ["provider", "model"],
)

KAFKA_PUBLISH_LATENCY_MS = Histogram(
    "kafka_publish_latency_ms",
    "Kafka publish latency in milliseconds.",
    ["topic"],
    buckets=_MS_BUCKETS,
)
KAFKA_MESSAGES_PRODUCED_TOTAL = Counter(
    "kafka_messages_produced_total",
    "Total messages produced to Kafka.",
    ["topic"],
)
KAFKA_MESSAGES_CONSUMED_TOTAL = Counter(
    "kafka_messages_consumed_total",
    "Total messages consumed from Kafka.",
    ["topic"],
)
KAFKA_CONSUMER_LAG = Gauge(
    "kafka_consumer_lag",
    "Consumer lag (records) per topic/partition.",
    ["topic", "partition"],
)

DB_INSERT_LATENCY_MS = Histogram(
    "db_insert_latency_ms",
    "Database insert latency in milliseconds.",
    ["table"],
    buckets=_MS_BUCKETS,
)
DB_ROWS_WRITTEN_TOTAL = Counter(
    "db_rows_written_total",
    "Total rows written to the database.",
    ["table"],
)

DLQ_MESSAGES_TOTAL = Counter(
    "dlq_messages_total",
    "Total messages routed to the dead-letter queue.",
    ["source", "reason"],
)

ACTIVE_CONVERSATIONS = Gauge(
    "active_conversations",
    "Number of active conversations (in-flight streaming sessions).",
)
ACTIVE_USERS = Gauge(
    "active_users",
    "Number of distinct users seen in the current window.",
)


def render_latest() -> tuple[bytes, str]:
    """Return the Prometheus exposition payload and its content type."""

    return generate_latest(), CONTENT_TYPE_LATEST
