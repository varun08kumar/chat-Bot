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
    xai_api_key: str | None = None

    # Web search tool (self-hosted SearXNG - see infra/searxng).
    searxng_url: str = "http://searxng:8080"
    web_search_max_results: int = 5

    # Auth (JWT access + refresh tokens, both set as httpOnly cookies).
    # No default for the secret — a service that can forge/verify session
    # tokens must not silently boot with a guessable one.
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_ttl_s: int = 180  # 3 minutes
    refresh_token_ttl_s: int = 7 * 24 * 3600  # 7 days
    # Cookies are Secure (HTTPS-only) outside local dev, where the stack is
    # plain HTTP end to end.
    cookie_secure: bool = False

    # Kafka (consumed from BaseServiceSettings + used to configure the SDK).
    inference_topic: str = "inference.logs"

    # Chat job queue (Redis Streams). Decouples "accept the request" from
    # "call the LLM provider": a request handler enqueues a job and relays
    # events back over Redis Pub/Sub rather than calling the provider
    # inline, so if the replica that accepted the request crashes
    # mid-response, any surviving replica's worker reclaims the still-
    # unacked job and finishes it — the reply gets computed and saved even
    # though that specific HTTP connection is gone.
    chat_job_stream: str = "chat:jobs"
    chat_job_group: str = "chat-workers"
    chat_job_claim_idle_ms: int = 30_000
    chat_job_claim_interval_s: float = 10.0
    chat_job_relay_timeout_s: float = 120.0
    # Every streamed token is also appended to a short-lived Redis key so
    # that if the worker crashes mid-stream, whichever worker reclaims the
    # orphaned job can persist exactly what was already shown to the user
    # instead of silently generating a different answer from scratch.
    chat_partial_ttl_s: int = 3600

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
