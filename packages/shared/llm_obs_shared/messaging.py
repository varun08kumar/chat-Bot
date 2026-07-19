"""Reusable Kafka producer/consumer helpers for the pipeline services.

Requires the ``kafka`` extra (``pip install llm-obs-shared[kafka]``). The SDK
ships its own tuned producer; these helpers are for the ingestion and consumer
services, keeping their Kafka wiring consistent and DRY.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from llm_obs_shared.logging import get_logger
from llm_obs_shared.metrics import (
    KAFKA_MESSAGES_PRODUCED_TOTAL,
    KAFKA_PUBLISH_LATENCY_MS,
)

logger = get_logger(__name__)


def _serialize(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        return value.model_dump_json().encode("utf-8")
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return json.dumps(value, default=str).encode("utf-8")


class JsonProducer:
    """Thin wrapper over ``AIOKafkaProducer`` for JSON payloads."""

    def __init__(self, bootstrap_servers: str, *, client_id: str, security_protocol: str = "PLAINTEXT") -> None:
        self._bootstrap = bootstrap_servers
        self._client_id = client_id
        self._security_protocol = security_protocol
        self._producer = None  # type: ignore[var-annotated]

    async def start(self) -> None:
        from aiokafka import AIOKafkaProducer

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap,
            client_id=self._client_id,
            security_protocol=self._security_protocol,
            enable_idempotence=True,
            acks="all",
            linger_ms=20,
        )
        await self._producer.start()

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def send(self, topic: str, value: Any, *, key: str | None = None) -> None:
        assert self._producer is not None, "producer not started"
        import time

        payload = _serialize(value)
        key_bytes = key.encode("utf-8") if key else None
        start = time.perf_counter()
        await self._producer.send_and_wait(topic, value=payload, key=key_bytes)
        KAFKA_PUBLISH_LATENCY_MS.labels(topic).observe((time.perf_counter() - start) * 1000)
        KAFKA_MESSAGES_PRODUCED_TOTAL.labels(topic).inc()


class DeadLetterPublisher:
    """Publishes un-processable messages to the dead-letter topic with context."""

    def __init__(self, producer: JsonProducer, topic: str = "dead-letter") -> None:
        self._producer = producer
        self._topic = topic

    async def publish(
        self,
        *,
        source_topic: str,
        reason: str,
        raw: bytes | str | None,
        key: str | None = None,
    ) -> None:
        envelope = {
            "source_topic": source_topic,
            "reason": reason,
            "payload": raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else raw,
        }
        try:
            await self._producer.send(self._topic, envelope, key=key)
        except Exception:  # noqa: BLE001 - never let DLQ failure crash the worker
            logger.exception("Failed to publish to dead-letter topic")


async def create_consumer(
    topics: list[str],
    *,
    group_id: str,
    bootstrap_servers: str,
    client_id: str,
    security_protocol: str = "PLAINTEXT",
    max_poll_records: int = 500,
):
    """Create and start a manual-commit ``AIOKafkaConsumer``.

    Manual commits give us at-least-once semantics: we only advance the offset
    after a message (or batch) is durably handled.
    """

    from aiokafka import AIOKafkaConsumer

    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        client_id=client_id,
        security_protocol=security_protocol,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        max_poll_records=max_poll_records,
    )
    await consumer.start()
    return consumer
