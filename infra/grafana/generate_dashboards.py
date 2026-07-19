#!/usr/bin/env python3
"""Generate Grafana dashboard JSON files from concise panel specs.

Run: ``python infra/grafana/generate_dashboards.py`` (re-run after edits).
Keeping the panels as Python data keeps the verbose JSON in one reproducible
place instead of being hand-maintained.
"""

from __future__ import annotations

import json
import os

DS = {"type": "prometheus", "uid": "prometheus"}
HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "dashboards")


def target(expr: str, legend: str = "", ref: str = "A") -> dict:
    return {"datasource": DS, "expr": expr, "legendFormat": legend, "refId": ref}


def stat(title: str, expr: str, unit: str, x: int, y: int, w: int = 6, h: int = 4, decimals=2) -> dict:
    return {
        "type": "stat",
        "title": title,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {"defaults": {"unit": unit, "decimals": decimals}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value", "graphMode": "area"},
        "targets": [target(expr)],
    }


def ts(title: str, targets: list[dict], unit: str, x: int, y: int, w: int = 12, h: int = 8) -> dict:
    return {
        "type": "timeseries",
        "title": title,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {
            "defaults": {"unit": unit, "custom": {"drawStyle": "line", "fillOpacity": 10, "lineWidth": 2}},
            "overrides": [],
        },
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
        "targets": targets,
    }


def dashboard(uid: str, title: str, panels: list[dict]) -> dict:
    for i, p in enumerate(panels, start=1):
        p["id"] = i
    return {
        "uid": uid,
        "title": title,
        "tags": ["llm-observability"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "10s",
        "time": {"from": "now-1h", "to": "now"},
        "templating": {"list": []},
        "annotations": {"list": []},
        "panels": panels,
    }


def llm_overview() -> dict:
    panels = [
        stat("Requests/sec", "sum(rate(llm_requests_total[1m]))", "reqps", 0, 0),
        stat(
            "Error rate",
            "sum(rate(llm_errors_total[5m])) / clamp_min(sum(rate(llm_requests_total[5m])), 0.0001)",
            "percentunit", 6, 0,
        ),
        stat(
            "P95 latency",
            "histogram_quantile(0.95, sum(rate(llm_latency_ms_bucket[5m])) by (le))",
            "ms", 12, 0,
        ),
        stat(
            "P99 latency",
            "histogram_quantile(0.99, sum(rate(llm_latency_ms_bucket[5m])) by (le))",
            "ms", 18, 0,
        ),
        ts(
            "LLM latency percentiles",
            [
                target("histogram_quantile(0.50, sum(rate(llm_latency_ms_bucket[5m])) by (le))", "p50", "A"),
                target("histogram_quantile(0.95, sum(rate(llm_latency_ms_bucket[5m])) by (le))", "p95", "B"),
                target("histogram_quantile(0.99, sum(rate(llm_latency_ms_bucket[5m])) by (le))", "p99", "C"),
            ],
            "ms", 0, 4,
        ),
        ts(
            "Requests by provider",
            [target("sum by (provider) (rate(llm_requests_total[1m]))", "{{provider}}")],
            "reqps", 12, 4,
        ),
        ts(
            "Errors by provider/model",
            [target("sum by (provider, model) (rate(llm_errors_total[5m]))", "{{provider}}/{{model}}")],
            "reqps", 0, 12,
        ),
        ts(
            "HTTP request rate by service",
            [target("sum by (service) (rate(http_requests_total[1m]))", "{{service}}")],
            "reqps", 12, 12,
        ),
    ]
    return dashboard("llmobs-overview", "LLM Overview", panels)


def kafka() -> dict:
    panels = [
        stat("Consumer lag (max)", "max(kafka_consumer_lag)", "short", 0, 0, decimals=0),
        stat("Produced/sec", "sum(rate(kafka_messages_produced_total[1m]))", "reqps", 6, 0),
        stat("Consumed/sec", "sum(rate(kafka_messages_consumed_total[1m]))", "reqps", 12, 0),
        stat("DLQ total", "sum(dlq_messages_total)", "short", 18, 0, decimals=0),
        ts(
            "Consumer lag by topic/partition",
            [target("kafka_consumer_lag", "{{topic}}-{{partition}}")],
            "short", 0, 4,
        ),
        ts(
            "Topic throughput",
            [
                target("sum by (topic) (rate(kafka_messages_produced_total[1m]))", "produced {{topic}}", "A"),
                target("sum by (topic) (rate(kafka_messages_consumed_total[1m]))", "consumed {{topic}}", "B"),
            ],
            "reqps", 12, 4,
        ),
        ts(
            "Kafka publish latency p95",
            [target("histogram_quantile(0.95, sum(rate(kafka_publish_latency_ms_bucket[5m])) by (le, topic))", "{{topic}}")],
            "ms", 0, 12,
        ),
        ts(
            "Dead-letter rate by reason",
            [target("sum by (source, reason) (rate(dlq_messages_total[5m]))", "{{source}}/{{reason}}")],
            "reqps", 12, 12,
        ),
    ]
    return dashboard("llmobs-kafka", "Kafka Pipeline", panels)


def database() -> dict:
    panels = [
        stat("Rows written/sec", "sum(rate(db_rows_written_total[1m]))", "reqps", 0, 0),
        stat(
            "Insert p95",
            "histogram_quantile(0.95, sum(rate(db_insert_latency_ms_bucket[5m])) by (le))",
            "ms", 6, 0,
        ),
        stat("Total rows written", "sum(db_rows_written_total)", "short", 12, 0, decimals=0),
        stat("Active conversations", "max(active_conversations)", "short", 18, 0, decimals=0),
        ts(
            "DB insert latency",
            [
                target("histogram_quantile(0.50, sum(rate(db_insert_latency_ms_bucket[5m])) by (le))", "p50", "A"),
                target("histogram_quantile(0.95, sum(rate(db_insert_latency_ms_bucket[5m])) by (le))", "p95", "B"),
                target("histogram_quantile(0.99, sum(rate(db_insert_latency_ms_bucket[5m])) by (le))", "p99", "C"),
            ],
            "ms", 0, 4,
        ),
        ts(
            "Insert throughput by table",
            [target("sum by (table) (rate(db_rows_written_total[1m]))", "{{table}}")],
            "reqps", 12, 4,
        ),
    ]
    return dashboard("llmobs-database", "Database", panels)


def application() -> dict:
    panels = [
        stat(
            "HTTP p95 (chat)",
            "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service=\"chat-service\"}[5m])) by (le))",
            "s", 0, 0,
        ),
        stat("Active users", "max(active_users)", "short", 6, 0, decimals=0),
        stat("5xx rate", "sum(rate(http_requests_total{status=~\"5..\"}[5m]))", "reqps", 12, 0),
        stat("Up services", "count(up == 1)", "short", 18, 0, decimals=0),
        ts(
            "HTTP request rate by service/status",
            [target("sum by (service, status) (rate(http_requests_total[1m]))", "{{service}} {{status}}")],
            "reqps", 0, 4,
        ),
        ts(
            "HTTP latency p95 by service",
            [target("histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service))", "{{service}}")],
            "s", 12, 4,
        ),
        ts("Target up/down", [target("up", "{{job}}")], "short", 0, 12),
    ]
    return dashboard("llmobs-application", "Application", panels)


def resources() -> dict:
    # Sourced from infra/docker/docker_stats_exporter.py (a host-side
    # `docker stats` wrapper - see its docstring for why cAdvisor isn't used
    # on Docker Desktop for Mac). Container names look like
    # "llm-observability-chat-service-1"; strip the project prefix/instance
    # suffix for a readable legend.
    strip = 'label_replace(label_replace(%s, "service", "$1", "name", "llm-observability-(.*)-[0-9]+"), "service", "$1", "name", "(.*)")'

    def by_service(expr: str) -> str:
        return strip % expr

    panels = [
        stat("Busiest container (CPU %)", "topk(1, container_cpu_percent)", "percent", 0, 0),
        stat("Total CPU across containers", "sum(container_cpu_percent)", "percent", 6, 0),
        stat("Total memory (RSS)", "sum(container_memory_usage_bytes)", "bytes", 12, 0),
        stat("Containers reporting", "count(container_cpu_percent)", "short", 18, 0, decimals=0),
        ts(
            "CPU usage by service (%)",
            [target(by_service("container_cpu_percent"), "{{service}}")],
            "percent", 0, 4,
        ),
        ts(
            "Memory usage by service",
            [target(by_service("container_memory_usage_bytes"), "{{service}}")],
            "bytes", 12, 4,
        ),
    ]
    return dashboard("llmobs-resources", "Container Resources", panels)


def kubernetes() -> dict:
    # From kube-state-metrics (infra/k8s/40-kube-state-metrics.yaml), scraped
    # via the `kind` docker network - see prometheus.yml's kubernetes-hpa job.
    hpa = 'horizontalpodautoscaler="chat-service"'
    panels = [
        stat("Current replicas", f"kube_horizontalpodautoscaler_status_current_replicas{{{hpa}}}", "short", 0, 0, decimals=0),
        stat("Desired replicas", f"kube_horizontalpodautoscaler_status_desired_replicas{{{hpa}}}", "short", 6, 0, decimals=0),
        stat("Max replicas", f"kube_horizontalpodautoscaler_spec_max_replicas{{{hpa}}}", "short", 12, 0, decimals=0),
        stat("Min replicas", f"kube_horizontalpodautoscaler_spec_min_replicas{{{hpa}}}", "short", 18, 0, decimals=0),
        ts(
            "chat-service replica count (HPA scaling under load)",
            [
                target(f"kube_horizontalpodautoscaler_status_current_replicas{{{hpa}}}", "current", "A"),
                target(f"kube_horizontalpodautoscaler_status_desired_replicas{{{hpa}}}", "desired", "B"),
            ],
            "short", 0, 4,
        ),
        ts(
            "Pod phase count (deployment: chat-service)",
            [target(
                'sum by (phase) (kube_pod_status_phase{namespace="llm-observability", pod=~"chat-service-.*"} == 1)',
                "{{phase}}",
            )],
            "short", 12, 4,
        ),
    ]
    return dashboard("llmobs-kubernetes", "Kubernetes Autoscaling", panels)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    files = {
        "llm_overview.json": llm_overview(),
        "kafka.json": kafka(),
        "database.json": database(),
        "application.json": application(),
        "resources.json": resources(),
        "kubernetes.json": kubernetes(),
    }
    for name, data in files.items():
        with open(os.path.join(OUT, name), "w") as fh:
            json.dump(data, fh, indent=2)
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
