"""Redis-backed conversation cache, session cache and rate limiter."""

from __future__ import annotations

import json
from typing import Any

from llm_obs_shared.logging import get_logger
from redis.asyncio import Redis

logger = get_logger(__name__)


class ConversationCache:
    """Caches recent messages per conversation to avoid hot-path DB reads."""

    def __init__(self, redis: Redis, *, ttl_s: int, max_messages: int) -> None:
        self._redis = redis
        self._ttl = ttl_s
        self._max_messages = max_messages

    @staticmethod
    def _key(conversation_id: str) -> str:
        return f"conv:{conversation_id}:messages"

    async def get_messages(self, conversation_id: str) -> list[dict[str, Any]] | None:
        try:
            raw = await self._redis.get(self._key(conversation_id))
        except Exception:  # noqa: BLE001 - cache is best-effort
            logger.warning("Redis get failed; falling back to DB")
            return None
        return json.loads(raw) if raw else None

    async def set_messages(self, conversation_id: str, messages: list[dict[str, Any]]) -> None:
        trimmed = messages[-self._max_messages :]
        try:
            await self._redis.set(self._key(conversation_id), json.dumps(trimmed), ex=self._ttl)
        except Exception:  # noqa: BLE001
            logger.warning("Redis set failed; skipping cache write")

    async def invalidate(self, conversation_id: str) -> None:
        try:
            await self._redis.delete(self._key(conversation_id))
        except Exception:  # noqa: BLE001
            pass


class RateLimiter:
    """Fixed-window rate limiter keyed by user id (or client IP fallback)."""

    def __init__(self, redis: Redis, *, limit: int, window_s: int, enabled: bool = True) -> None:
        self._redis = redis
        self._limit = limit
        self._window = window_s
        self._enabled = enabled

    async def check(self, identity: str) -> tuple[bool, int]:
        """Return (allowed, remaining). Fails open if Redis is unavailable."""

        if not self._enabled:
            return True, self._limit
        key = f"ratelimit:{identity}"
        try:
            current = await self._redis.incr(key)
            if current == 1:
                await self._redis.expire(key, self._window)
            remaining = max(0, self._limit - current)
            return current <= self._limit, remaining
        except Exception:  # noqa: BLE001 - never block requests on limiter failure
            logger.warning("Rate limiter unavailable; failing open")
            return True, self._limit
