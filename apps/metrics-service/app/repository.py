"""Read-only aggregation queries for the dashboard APIs.

All queries are parameterised (no string interpolation of user input),
scoped to a time window, and scoped to the requesting user — this is a
personal usage dashboard, not an admin view (that's the "Per-User Usage"
Grafana dashboard, which is intentionally NOT user-scoped and lives behind
Grafana's own separate login). Time series are bucketed with
``to_timestamp(floor(epoch / bucket) * bucket)`` so any bucket width works
with a single query shape.
"""

from __future__ import annotations

from typing import Any

from llm_obs_shared.db.session import Database
from sqlalchemy import text

from app.window import TimeWindow

_SUCCESS = "success"


class MetricsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def _rows(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        async with self._db.session() as session:
            result = await session.execute(text(sql), params)
            return [dict(row) for row in result.mappings().all()]

    async def _row(self, sql: str, params: dict[str, Any]) -> dict[str, Any]:
        rows = await self._rows(sql, params)
        return rows[0] if rows else {}

    async def providers(self, window: TimeWindow, user_id: str) -> list[dict[str, Any]]:
        sql = """
            SELECT provider,
                   COUNT(*)                                    AS requests,
                   COUNT(*) FILTER (WHERE status <> :success)  AS errors,
                   COALESCE(AVG(latency_ms), 0)                AS avg_latency_ms,
                   COALESCE(SUM(total_tokens), 0)              AS total_tokens
            FROM inference_logs
            WHERE timestamp >= :since AND user_id = :user_id
            GROUP BY provider
            ORDER BY requests DESC
        """
        rows = await self._rows(sql, {"since": window.since, "success": _SUCCESS, "user_id": user_id})
        for row in rows:
            row["error_rate"] = _rate(row["errors"], row["requests"])
        return rows

    async def models(self, window: TimeWindow, user_id: str) -> list[dict[str, Any]]:
        sql = """
            SELECT model,
                   provider,
                   COUNT(*)                                    AS requests,
                   COUNT(*) FILTER (WHERE status <> :success)  AS errors,
                   COALESCE(AVG(latency_ms), 0)                AS avg_latency_ms,
                   COALESCE(SUM(prompt_tokens), 0)             AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0)         AS completion_tokens,
                   COALESCE(SUM(total_tokens), 0)              AS total_tokens
            FROM inference_logs
            WHERE timestamp >= :since AND user_id = :user_id
            GROUP BY model, provider
            ORDER BY requests DESC
        """
        rows = await self._rows(sql, {"since": window.since, "success": _SUCCESS, "user_id": user_id})
        for row in rows:
            row["error_rate"] = _rate(row["errors"], row["requests"])
        return rows

    async def latency_summary(self, window: TimeWindow, user_id: str) -> dict[str, Any]:
        sql = """
            SELECT COALESCE(AVG(latency_ms), 0)                                          AS avg_ms,
                   COALESCE(percentile_cont(0.50) WITHIN GROUP (ORDER BY latency_ms), 0) AS p50_ms,
                   COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms), 0) AS p95_ms,
                   COALESCE(percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms), 0) AS p99_ms,
                   COALESCE(MAX(latency_ms), 0)                                          AS max_ms,
                   COUNT(*)                                                              AS samples
            FROM inference_logs
            WHERE timestamp >= :since AND user_id = :user_id
        """
        return await self._row(sql, {"since": window.since, "user_id": user_id})

    async def latency_series(self, window: TimeWindow, user_id: str) -> list[dict[str, Any]]:
        sql = """
            SELECT to_timestamp(floor(extract(epoch FROM timestamp) / :bucket) * :bucket) AS bucket,
                   COALESCE(AVG(latency_ms), 0)                                          AS avg_ms,
                   COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms), 0) AS p95_ms,
                   COALESCE(percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms), 0) AS p99_ms
            FROM inference_logs
            WHERE timestamp >= :since AND user_id = :user_id
            GROUP BY bucket
            ORDER BY bucket
        """
        return await self._rows(sql, {"since": window.since, "bucket": window.bucket_seconds, "user_id": user_id})

    async def throughput_series(self, window: TimeWindow, user_id: str) -> list[dict[str, Any]]:
        sql = """
            SELECT to_timestamp(floor(extract(epoch FROM timestamp) / :bucket) * :bucket) AS bucket,
                   COUNT(*)                                                              AS requests,
                   COUNT(*)::float / :bucket                                             AS rps
            FROM inference_logs
            WHERE timestamp >= :since AND user_id = :user_id
            GROUP BY bucket
            ORDER BY bucket
        """
        return await self._rows(sql, {"since": window.since, "bucket": window.bucket_seconds, "user_id": user_id})

    async def errors_series(self, window: TimeWindow, user_id: str) -> list[dict[str, Any]]:
        sql = """
            SELECT to_timestamp(floor(extract(epoch FROM timestamp) / :bucket) * :bucket) AS bucket,
                   COUNT(*)                                    AS total,
                   COUNT(*) FILTER (WHERE status <> :success)  AS errors
            FROM inference_logs
            WHERE timestamp >= :since AND user_id = :user_id
            GROUP BY bucket
            ORDER BY bucket
        """
        rows = await self._rows(
            sql, {"since": window.since, "bucket": window.bucket_seconds, "success": _SUCCESS, "user_id": user_id}
        )
        for row in rows:
            row["error_rate"] = _rate(row["errors"], row["total"])
        return rows

    async def recent_errors(self, window: TimeWindow, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        sql = """
            SELECT request_id, provider, model, status, error, latency_ms, timestamp
            FROM inference_logs
            WHERE timestamp >= :since AND status <> :success AND user_id = :user_id
            ORDER BY timestamp DESC
            LIMIT :limit
        """
        return await self._rows(sql, {"since": window.since, "success": _SUCCESS, "user_id": user_id, "limit": limit})

    async def tokens(self, window: TimeWindow, user_id: str) -> dict[str, Any]:
        totals = await self._row(
            """
            SELECT COALESCE(SUM(prompt_tokens), 0)     AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(total_tokens), 0)      AS total_tokens
            FROM inference_logs
            WHERE timestamp >= :since AND user_id = :user_id
            """,
            {"since": window.since, "user_id": user_id},
        )
        by_provider = await self._rows(
            """
            SELECT provider,
                   COALESCE(SUM(prompt_tokens), 0)     AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(total_tokens), 0)      AS total_tokens
            FROM inference_logs
            WHERE timestamp >= :since AND user_id = :user_id
            GROUP BY provider
            ORDER BY total_tokens DESC
            """,
            {"since": window.since, "user_id": user_id},
        )
        return {"totals": totals, "by_provider": by_provider}

    async def summary(self, window: TimeWindow, user_id: str) -> dict[str, Any]:
        sql = """
            SELECT COUNT(*)                                                              AS total_requests,
                   COUNT(*) FILTER (WHERE status <> :success)                            AS total_errors,
                   COUNT(DISTINCT conversation_id)                                       AS conversations,
                   COALESCE(AVG(latency_ms), 0)                                          AS avg_latency_ms,
                   COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms), 0) AS p95_latency_ms,
                   COALESCE(percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms), 0) AS p99_latency_ms,
                   COALESCE(SUM(total_tokens), 0)                                        AS total_tokens
            FROM inference_logs
            WHERE timestamp >= :since AND user_id = :user_id
        """
        row = await self._row(sql, {"since": window.since, "success": _SUCCESS, "user_id": user_id})
        requests = row.get("total_requests", 0) or 0
        row["error_rate"] = _rate(row.get("total_errors", 0), requests)
        row["requests_per_second"] = round(requests / window.lookback_seconds, 4) if window.lookback_seconds else 0.0
        return row


def _rate(errors: Any, total: Any) -> float:
    total = float(total or 0)
    if total <= 0:
        return 0.0
    return round(float(errors or 0) / total, 4)
