"""Non-blocking async Kafka producer for inference events.

Design goals (in priority order):

1. **Never block inference.** ``emit`` only enqueues; it never awaits a network
   round-trip. If the buffer is full the *oldest* event is dropped so a slow or
   unavailable Kafka broker exerts back-pressure on logs, never on user
   requests.
2. **Never crash the caller.** Every failure path is swallowed and counted; a
   logging failure must not surface as an inference failure.
3. **At-least-once delivery when healthy.** A background worker drains the queue
   and retries transient send failures with bounded attempts.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from llm_obs_shared.logging import get_logger
from llm_obs_shared.metrics import (
    KAFKA_MESSAGES_PRODUCED_TOTAL,
    KAFKA_PUBLISH_LATENCY_MS,
)
from llm_obs_shared.schemas import InferenceLogEvent

from llm_obs_sdk.config import SdkConfig

logger = get_logger(__name__)


class KafkaLogProducer:
    """Buffered, fire-and-forget producer of :class:`InferenceLogEvent`."""

    def __init__(self, config: SdkConfig) -> None:
        self._config = config
        self._queue: asyncio.Queue[InferenceLogEvent] = asyncio.Queue(maxsize=config.queue_max_size)
        self._producer = None  # type: ignore[var-annotated]
        self._worker: Optional[asyncio.Task] = None
        self._started = False
        self._dropped = 0

    async def start(self) -> None:
        """Create the underlying aiokafka producer and launch the drain worker."""

        if self._started or not self._config.enabled:
            return
        # Imported lazily so importing the SDK never hard-requires aiokafka at
        # module import time (helps unit tests and the no-op path).
        from aiokafka import AIOKafkaProducer

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._config.bootstrap_servers,
            client_id=self._config.client_id,
            security_protocol=self._config.security_protocol,
            enable_idempotence=True,
            acks="all",
            linger_ms=20,
            request_timeout_ms=10_000,
        )
        await self._producer.start()
        self._worker = asyncio.create_task(self._drain(), name="sdk-kafka-drain")
        self._started = True
        logger.info("SDK Kafka producer started", extra={"topic": self._config.topic})

    async def stop(self) -> None:
        """Flush outstanding events and shut the producer down gracefully."""

        if not self._started:
            return
        self._started = False
        if self._worker is not None:
            try:
                await asyncio.wait_for(self._queue.join(), timeout=self._config.flush_timeout_s)
            except asyncio.TimeoutError:
                logger.warning("Timed out flushing SDK queue on shutdown")
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
        if self._producer is not None:
            await self._producer.stop()
        logger.info("SDK Kafka producer stopped", extra={"dropped_events": self._dropped})

    def emit(self, event: InferenceLogEvent) -> None:
        """Enqueue an event without blocking. Drops oldest on overflow."""

        if not self._config.enabled:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # Drop the oldest event to make room — bounded memory beats blocking.
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                self._dropped += 1
            except asyncio.QueueEmpty:  # pragma: no cover - race, harmless
                pass
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - extreme back-pressure
                self._dropped += 1

    async def _drain(self) -> None:
        assert self._producer is not None
        loop = asyncio.get_running_loop()
        while True:
            event = await self._queue.get()
            try:
                await self._send_with_retry(event, loop)
            except asyncio.CancelledError:
                # Re-queue for the flush path is not possible after cancel; just exit.
                self._queue.task_done()
                raise
            except Exception:  # noqa: BLE001 - logging must never crash the worker
                logger.exception("Failed to publish inference event; dropping")
            finally:
                self._queue.task_done()

    async def _send_with_retry(self, event: InferenceLogEvent, loop) -> None:
        payload = event.model_dump_json().encode("utf-8")
        key = (event.conversation_id or event.request_id).encode("utf-8")
        attempt = 0
        while True:
            attempt += 1
            start = loop.time()
            try:
                await self._producer.send_and_wait(self._config.topic, value=payload, key=key)
                KAFKA_PUBLISH_LATENCY_MS.labels(self._config.topic).observe((loop.time() - start) * 1000)
                KAFKA_MESSAGES_PRODUCED_TOTAL.labels(self._config.topic).inc()
                return
            except Exception:  # noqa: BLE001
                if attempt > self._config.send_max_retries:
                    self._dropped += 1
                    logger.warning(
                        "Dropping inference event after retries",
                        extra={"request_id": event.request_id, "attempts": attempt},
                    )
                    return
                # Exponential backoff, capped, without ever blocking inference.
                await asyncio.sleep(min(0.1 * (2 ** (attempt - 1)), 2.0))
