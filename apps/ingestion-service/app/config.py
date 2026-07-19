"""Ingestion service configuration."""

from __future__ import annotations

from functools import lru_cache

from llm_obs_shared.settings import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "ingestion-service"

    host: str = "0.0.0.0"
    port: int = 8002

    # Kafka topics / group
    inference_topic: str = "inference.logs"
    processed_topic: str = "processed.logs"
    dead_letter_topic: str = "dead-letter"
    consumer_group: str = "ingestion-service"
    max_poll_records: int = 500

    # PII redaction toggle (kept configurable for regulated vs. dev environments).
    pii_redaction_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
