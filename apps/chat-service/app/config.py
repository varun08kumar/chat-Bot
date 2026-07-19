"""Chat service configuration (env-driven)."""

from __future__ import annotations

from functools import lru_cache

from llm_obs_shared.settings import BaseServiceSettings
from pydantic import Field


class Settings(BaseServiceSettings):
    service_name: str = "chat-service"

    # HTTP
    host: str = "0.0.0.0"
    port: int = 8001
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"])

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/llm_observability"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    conversation_cache_ttl_s: int = 3600
    recent_messages_cache: int = 20

    # Rate limiting (fixed window per user).
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 60
    rate_limit_window_s: int = 60

    # LLM
    default_provider: str = "openai"
    default_model: str = "gpt-4o-mini"
    llm_timeout_s: float = 60.0
    max_history_messages: int = 30
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    groq_api_key: str | None = None
    gemini_api_key: str | None = None

    # Kafka (consumed from BaseServiceSettings + used to configure the SDK).
    inference_topic: str = "inference.logs"

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
