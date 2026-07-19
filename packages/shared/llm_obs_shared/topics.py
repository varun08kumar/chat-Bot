"""Canonical Kafka topic names shared across producers and consumers.

Keeping these in one place prevents drift between services (a producer writing
to ``inference.logs`` while a consumer subscribes to ``inference_logs``).
"""

from __future__ import annotations

from enum import Enum


class Topics(str, Enum):
    """Kafka topics used by the platform."""

    INFERENCE_LOGS = "inference.logs"
    PROCESSED_LOGS = "processed.logs"
    DEAD_LETTER = "dead-letter"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


#: Consumer group ids, colocated with the topic definitions for discoverability.
class ConsumerGroups(str, Enum):
    INGESTION = "ingestion-service"
    CONSUMER = "consumer-service"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value
