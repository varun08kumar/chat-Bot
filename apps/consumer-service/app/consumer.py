"""Consume ``processed.logs`` and persist to PostgreSQL in batches.

Reliability properties:

* **Batching** — each poll yields up to ``batch_max_size`` records written in a
  single transaction.
* **Idempotency** — inserts use ``ON CONFLICT DO NOTHING`` so replays after a
  crash (resume-from-committed-offset) never duplicate rows.
* **Retry + backoff** — transient DB failures are retried with exponential
  backoff; offsets are only committed after a durable write.
* **Dead-letter** — messages that fail validation, or a batch that fails every
  retry, are routed to the dead-letter topic so the partition never stalls.
* **Graceful shutdown** — the loop drains and commits before exiting.
"""

from __future__ import annotations

import asyncio
import json

from llm_obs_shared.logging import get_logger
from llm_obs_shared.messaging import DeadLetterPublisher, JsonProducer, create_consumer
from llm_obs_shared.metrics import (
    DLQ_MESSAGES_TOTAL,
    KAFKA_CONSUMER_LAG,
    KAFKA_MESSAGES_CONSUMED_TOTAL,
)
from llm_obs_shared.schemas import ProcessedLogEvent
from pydantic import ValidationError

from app.config import Settings
from app.repository import InferenceLogRepository

logger = get_logger(__name__)


class PersistenceConsumer:
    def __init__(self, settings: Settings, repository: InferenceLogRepository) -> None:
        self._settings = settings
        self._repo = repository
        self._consumer = None
        self._producer = JsonProducer(
            settings.kafka_bootstrap_servers,
            client_id=f"{settings.service_name}-producer",
            security_protocol=settings.kafka_security_protocol,
        )
        self._dlq = DeadLetterPublisher(self._producer, topic=settings.dead_letter_topic)
        self._stop = asyncio.Event()
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        await self._producer.start()
        self._consumer = await create_consumer(
            [self._settings.processed_topic],
            group_id=self._settings.consumer_group,
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            client_id=f"{self._settings.service_name}-consumer",
            security_protocol=self._settings.kafka_security_protocol,
            max_poll_records=self._settings.max_poll_records,
        )
        self._running = True
        logger.info("Persistence consumer started", extra={"topic": self._settings.processed_topic})

    async def run(self) -> None:
        assert self._consumer is not None
        try:
            while not self._stop.is_set():
                batches = await self._consumer.getmany(
                    timeout_ms=self._settings.batch_max_wait_ms,
                    max_records=self._settings.batch_max_size,
                )
                if not batches:
                    continue

                valid: list[ProcessedLogEvent] = []
                for tp, messages in batches.items():
                    KAFKA_MESSAGES_CONSUMED_TOTAL.labels(tp.topic).inc(len(messages))
                    for message in messages:
                        event = await self._parse(message)
                        if event is not None:
                            valid.append(event)
                    await self._update_lag(tp)

                # Persist valid rows durably, then commit — at-least-once.
                await self._persist_with_retry(valid)
                await self._consumer.commit()
        except asyncio.CancelledError:
            raise
        finally:
            await self.stop()

    async def _parse(self, message) -> ProcessedLogEvent | None:
        try:
            data = json.loads(message.value)
            return ProcessedLogEvent.model_validate(data)
        except (json.JSONDecodeError, ValidationError, UnicodeDecodeError) as exc:
            DLQ_MESSAGES_TOTAL.labels("consumer-service", "invalid").inc()
            # Await the DLQ write so it is durable before we commit the offset.
            await self._dlq.publish(
                source_topic=self._settings.processed_topic,
                reason=f"parse/validation error: {exc}",
                raw=message.value,
            )
            logger.warning("Routed invalid processed event to DLQ")
            return None

    async def _persist_with_retry(self, events: list[ProcessedLogEvent]) -> None:
        if not events:
            return
        attempt = 0
        while True:
            try:
                written = await self._repo.insert_batch(events)
                logger.info("Persisted batch", extra={"received": len(events), "written": written})
                return
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                if attempt > self._settings.write_max_retries:
                    DLQ_MESSAGES_TOTAL.labels("consumer-service", "write_failed").inc(len(events))
                    logger.error(
                        "Batch failed after retries; routing to DLQ",
                        extra={"size": len(events), "error": str(exc)},
                    )
                    for event in events:
                        await self._dlq.publish(
                            source_topic=self._settings.processed_topic,
                            reason=f"db write failed: {exc}",
                            raw=event.model_dump_json(),
                            key=event.request_id,
                        )
                    return
                backoff = min(
                    self._settings.write_backoff_base_s * (2 ** (attempt - 1)),
                    self._settings.write_backoff_max_s,
                )
                logger.warning(
                    "DB write failed; backing off",
                    extra={"attempt": attempt, "backoff_s": backoff, "error": str(exc)},
                )
                await asyncio.sleep(backoff)

    async def _update_lag(self, tp) -> None:
        try:
            end_offsets = await self._consumer.end_offsets([tp])
            position = await self._consumer.position(tp)
            KAFKA_CONSUMER_LAG.labels(tp.topic, str(tp.partition)).set(max(0, end_offsets[tp] - position))
        except Exception:  # noqa: BLE001
            pass

    def request_stop(self) -> None:
        self._stop.set()

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._consumer is not None:
            try:
                await self._consumer.commit()
            except Exception:  # noqa: BLE001
                pass
            await self._consumer.stop()
        await self._producer.stop()
        logger.info("Persistence consumer stopped")
