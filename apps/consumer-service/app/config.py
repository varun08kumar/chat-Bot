"""Consumer service configuration."""

from __future__ import annotations

from functools import lru_cache

from llm_obs_shared.settings import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "consumer-service"

    host: str = "0.0.0.0"
    port: int = 8003

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/llm_observability"
    db_pool_size: int = 10
    db_max_overflow: int = 10

    processed_topic: str = "processed.logs"
    dead_letter_topic: str = "dead-letter"
    consumer_group: str = "consumer-service"

    # Batching
    batch_max_size: int = 200
    batch_max_wait_ms: int = 1000
    max_poll_records: int = 500

    # Retry / backoff for DB writes
    write_max_retries: int = 5
    write_backoff_base_s: float = 0.2
    write_backoff_max_s: float = 10.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
