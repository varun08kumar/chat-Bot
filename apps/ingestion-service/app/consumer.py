"""The ingestion consume loop.

Reads from ``inference.logs``, processes each message and publishes the result
to ``processed.logs``. Invalid messages are routed to the dead-letter topic so a
single poison message never stalls the partition. Offsets are committed only
after a message is durably handled (at-least-once).
"""

from __future__ import annotations

import asyncio

from llm_obs_shared.logging import get_logger
from llm_obs_shared.messaging import DeadLetterPublisher, JsonProducer, create_consumer
from llm_obs_shared.metrics import (
    DLQ_MESSAGES_TOTAL,
    KAFKA_CONSUMER_LAG,
    KAFKA_MESSAGES_CONSUMED_TOTAL,
)

from app.config import Settings
from app.processor import EventProcessor, InvalidEventError

logger = get_logger(__name__)


class IngestionConsumer:
    def __init__(self, settings: Settings, processor: EventProcessor) -> None:
        self._settings = settings
        self._processor = processor
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
            [self._settings.inference_topic],
            group_id=self._settings.consumer_group,
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            client_id=f"{self._settings.service_name}-consumer",
            security_protocol=self._settings.kafka_security_protocol,
            max_poll_records=self._settings.max_poll_records,
        )
        self._running = True
        logger.info("Ingestion consumer started", extra={"topic": self._settings.inference_topic})

    async def run(self) -> None:
        """Main loop. Returns when :meth:`stop` is signalled."""

        assert self._consumer is not None
        try:
            while not self._stop.is_set():
                batches = await self._consumer.getmany(timeout_ms=1000, max_records=self._settings.max_poll_records)
                for tp, messages in batches.items():
                    for message in messages:
                        await self._handle(message)
                    await self._update_lag(tp)
                if batches:
                    await self._consumer.commit()
        except asyncio.CancelledError:
            raise
        finally:
            await self.stop()

    async def _handle(self, message) -> None:
        KAFKA_MESSAGES_CONSUMED_TOTAL.labels(self._settings.inference_topic).inc()
        try:
            processed = self._processor.process(message.value)
        except InvalidEventError as exc:
            DLQ_MESSAGES_TOTAL.labels("ingestion-service", "invalid").inc()
            await self._dlq.publish(
                source_topic=self._settings.inference_topic,
                reason=str(exc),
                raw=message.value,
                key=message.key.decode("utf-8") if message.key else None,
            )
            logger.warning("Routed invalid event to DLQ", extra={"reason": str(exc)})
            return
        try:
            await self._producer.send(
                self._settings.processed_topic,
                processed,
                key=processed.conversation_id or processed.request_id,
            )
        except Exception as exc:  # noqa: BLE001
            # Publishing failure is retriable — re-raise to avoid committing the
            # offset so the message is re-processed after a rebalance/restart.
            logger.exception("Failed to publish processed event")
            raise

    async def _update_lag(self, tp) -> None:
        try:
            end_offsets = await self._consumer.end_offsets([tp])
            position = await self._consumer.position(tp)
            lag = max(0, end_offsets[tp] - position)
            KAFKA_CONSUMER_LAG.labels(tp.topic, str(tp.partition)).set(lag)
        except Exception:  # noqa: BLE001 - lag reporting is best-effort
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
        logger.info("Ingestion consumer stopped")
