"""Dependency-injection wiring.

A single ``AppContainer`` is built during the FastAPI lifespan and stored on
``app.state``. Route handlers receive collaborators via ``Depends`` providers so
they never construct their own database or Redis connections.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from llm_obs_shared.db.session import Database
from redis.asyncio import Redis

from app.config import Settings, get_settings
from app.services.cache import ConversationCache, RateLimiter
from app.services.chat_service import ChatService
from app.services.llm_client import LLMClient


@dataclass
class AppContainer:
    settings: Settings
    database: Database
    redis: Redis
    cache: ConversationCache
    rate_limiter: RateLimiter
    llm: LLMClient
    chat_service: ChatService

    @classmethod
    def build(cls, settings: Settings) -> "AppContainer":
        database = Database(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )
        redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        cache = ConversationCache(
            redis, ttl_s=settings.conversation_cache_ttl_s, max_messages=settings.recent_messages_cache
        )
        rate_limiter = RateLimiter(
            redis,
            limit=settings.rate_limit_requests,
            window_s=settings.rate_limit_window_s,
            enabled=settings.rate_limit_enabled,
        )
        llm = LLMClient(settings)
        chat_service = ChatService(db=database, cache=cache, llm=llm, settings=settings)
        return cls(
            settings=settings,
            database=database,
            redis=redis,
            cache=cache,
            rate_limiter=rate_limiter,
            llm=llm,
            chat_service=chat_service,
        )

    async def aclose(self) -> None:
        await self.database.dispose()
        await self.redis.aclose()


def container(request: Request) -> AppContainer:
    return request.app.state.container


def get_chat_service(c: AppContainer = Depends(container)) -> ChatService:
    return c.chat_service


def get_rate_limiter(c: AppContainer = Depends(container)) -> RateLimiter:
    return c.rate_limiter


def get_db(c: AppContainer = Depends(container)) -> Database:
    return c.database


@dataclass(frozen=True)
class Identity:
    user_id: str
    session_id: str


def get_identity(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> Identity:
    """Resolve caller identity from headers, with dev-friendly defaults.

    In production these headers would be populated by an auth gateway; for the
    assessment we accept them directly and fall back to a demo identity.
    """

    return Identity(
        user_id=x_user_id or "demo-user",
        session_id=x_session_id or uuid.uuid4().hex,
    )


def settings_dep() -> Settings:
    return get_settings()
