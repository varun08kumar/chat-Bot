"""Reusable Pydantic-settings mixins for configuration via environment.

Services subclass ``BaseServiceSettings`` and add their own fields. All config
comes from the environment (12-factor); secrets are never committed.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    """Common settings every service shares."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = "llm-obs-service"
    environment: str = "development"
    log_level: str = "INFO"

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9094"
    kafka_client_id: str = "llm-obs"
    kafka_security_protocol: str = "PLAINTEXT"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}
