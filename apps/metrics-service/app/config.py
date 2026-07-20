"""Metrics service configuration."""

from __future__ import annotations

from functools import lru_cache

from llm_obs_shared.settings import BaseServiceSettings
from pydantic import Field


class Settings(BaseServiceSettings):
    service_name: str = "metrics-service"

    host: str = "0.0.0.0"
    port: int = 8004
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"])

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/llm_observability"
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # Verify-only: the dashboard is scoped to the requesting user, so this
    # service needs to read (not issue) the same access-token cookie
    # chat-service sets — see app/services/auth.py.
    jwt_secret: str
    jwt_algorithm: str = "HS256"


@lru_cache
def get_settings() -> Settings:
    return Settings()
