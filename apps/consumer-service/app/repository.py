"""Batch persistence for processed inference events.

Uses PostgreSQL ``INSERT ... ON CONFLICT`` for idempotent, high-throughput
writes (a replayed message never double-inserts thanks to the unique
``request_id``), and maintains the ``provider_stats`` rollup in the same
transaction.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone

from llm_obs_shared.db.models import InferenceLog, ProviderStats
from llm_obs_shared.db.session import Database
from llm_obs_shared.logging import get_logger
from llm_obs_shared.metrics import DB_INSERT_LATENCY_MS, DB_ROWS_WRITTEN_TOTAL
from llm_obs_shared.schemas import InferenceStatus, ProcessedLogEvent
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = get_logger(__name__)


class InferenceLogRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert_batch(self, events: list[ProcessedLogEvent]) -> int:
        """Insert a batch idempotently and update provider stats. Returns rows written."""

        if not events:
            return 0

        rows = [self._to_row(event) for event in events]
        started = time.perf_counter()
        async with self._db.session() as session:
            # Insert against the Table (real column names) so the reserved
            # attribute name "metadata" doesn't collide with ORM bulk mapping.
            # RETURNING tells us which rows were *actually* new, so the
            # provider_stats rollup stays correct even when a batch is replayed
            # after a crash (at-least-once) — the idempotent insert writes 0 rows
            # and the rollup is updated for 0 events.
            stmt = (
                pg_insert(InferenceLog.__table__)
                .values(rows)
                .on_conflict_do_nothing(index_elements=["request_id"])
                .returning(InferenceLog.__table__.c.request_id)
            )
            result = await session.execute(stmt)
            inserted_ids = {row[0] for row in result}
            inserted_events = [e for e in events if e.request_id in inserted_ids]
            await self._update_provider_stats(session, inserted_events)
        elapsed_ms = (time.perf_counter() - started) * 1000
        DB_INSERT_LATENCY_MS.labels("inference_logs").observe(elapsed_ms)
        written = len(inserted_ids)
        DB_ROWS_WRITTEN_TOTAL.labels("inference_logs").inc(written)
        return written

    @staticmethod
    def _to_row(event: ProcessedLogEvent) -> dict:
        return {
            "request_id": event.request_id,
            "correlation_id": event.correlation_id,
            "conversation_id": event.conversation_id,
            "session_id": event.session_id,
            "user_id": event.user_id,
            "provider": event.provider,
            "model": event.model,
            "endpoint": event.endpoint,
            "latency_ms": event.latency_ms,
            "status": str(event.status),
            "error": event.error,
            "prompt_preview": event.prompt_preview[:256],
            "response_preview": event.response_preview[:256],
            "prompt_tokens": event.prompt_tokens,
            "completion_tokens": event.completion_tokens,
            "total_tokens": event.total_tokens,
            "metadata": event.metadata or {},
            "timestamp": event.timestamp,
        }

    async def _update_provider_stats(self, session, events: list[ProcessedLogEvent]) -> None:
        # Aggregate this batch per provider.
        agg: dict[str, dict[str, float]] = defaultdict(lambda: {"requests": 0, "errors": 0, "sum_latency": 0.0})
        for event in events:
            bucket = agg[event.provider]
            bucket["requests"] += 1
            if str(event.status) != InferenceStatus.SUCCESS.value:
                bucket["errors"] += 1
            bucket["sum_latency"] += event.latency_ms

        now = datetime.now(timezone.utc)
        for provider, bucket in agg.items():
            requests = int(bucket["requests"])
            batch_avg = bucket["sum_latency"] / requests if requests else 0.0
            stmt = pg_insert(ProviderStats).values(
                provider=provider,
                requests=requests,
                errors=int(bucket["errors"]),
                avg_latency=batch_avg,
                updated_at=now,
            )
            # Weighted running average: EXCLUDED.avg_latency * EXCLUDED.requests == batch sum.
            stmt = stmt.on_conflict_do_update(
                index_elements=[ProviderStats.provider],
                set_={
                    "requests": ProviderStats.requests + stmt.excluded.requests,
                    "errors": ProviderStats.errors + stmt.excluded.errors,
                    "avg_latency": (
                        (ProviderStats.avg_latency * ProviderStats.requests)
                        + (stmt.excluded.avg_latency * stmt.excluded.requests)
                    )
                    / (ProviderStats.requests + stmt.excluded.requests),
                    "updated_at": now,
                },
            )
            await session.execute(stmt)
