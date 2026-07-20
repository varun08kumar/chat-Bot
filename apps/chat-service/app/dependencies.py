"""Dependency-injection wiring.

A single ``AppContainer`` is built during the FastAPI lifespan and stored on
``app.state``. Route handlers receive collaborators via ``Depends`` providers so
they never construct their own database or Redis connections.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from llm_obs_shared.db.session import Database
from redis.asyncio import Redis

from app.config import Settings, get_settings
from app.services.auth import TokenError, verify_token
from app.services.cache import ConversationCache, RateLimiter
from app.services.chat_service import ChatService
from app.services.job_queue import ChatJobQueue
from app.services.llm_client import LLMClient


@dataclass
class AppContainer:
    settings: Settings
    database: Database
    redis: Redis
    cache: ConversationCache
    rate_limiter: RateLimiter
    llm: LLMClient
    job_queue: ChatJobQueue
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
        job_queue = ChatJobQueue(redis, stream=settings.chat_job_stream, group=settings.chat_job_group)
        chat_service = ChatService(
            db=database, cache=cache, llm=llm, settings=settings, redis=redis, job_queue=job_queue
        )
        return cls(
            settings=settings,
            database=database,
            redis=redis,
            cache=cache,
            rate_limiter=rate_limiter,
            llm=llm,
            job_queue=job_queue,
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
    access_token: str | None = Cookie(default=None, alias="access_token"),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
    settings: Settings = Depends(get_settings),
) -> Identity:
    """Resolve caller identity from the verified JWT access-token cookie.

    `user_id` now comes only from a token's `sub` claim, signed server-side
    at login/refresh — this replaces an earlier version that trusted
    whatever `X-User-Id` header the client happened to send, which let any
    caller claim to be any user. `session_id` isn't a security boundary
    (just a correlation label for the observability SDK, e.g. distinguishing
    browser tabs of the same logged-in user), so it's still client-supplied.
    """

    if access_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = verify_token(access_token, expected_type="access", settings=settings)
    except TokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    return Identity(
        user_id=payload.user_id,
        session_id=x_session_id or uuid.uuid4().hex,
    )


def verify_csrf(
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    csrf_token: str | None = Cookie(default=None, alias="csrf_token"),
) -> None:
    """Double-submit CSRF check, required on every state-changing route.

    httpOnly session cookies are attached by the browser to *any* site's
    request to this origin — that's what makes CSRF possible even though
    the cookies themselves can't be read or forged by an attacker's page.
    `csrf_token` is deliberately NOT httpOnly, so only JavaScript actually
    running on this origin can read it and echo it back as a header; a
    cross-site form or script has no way to produce a matching value.
    """

    if not x_csrf_token or not csrf_token or not secrets.compare_digest(x_csrf_token, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing or invalid")


def settings_dep() -> Settings:
    return get_settings()
