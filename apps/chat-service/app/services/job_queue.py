"""Redis Streams job queue for chat completions.

Durability model: the HTTP handler enqueues a job *after* the user's
message is already persisted to Postgres (see ``ChatService.prepare``),
then relays live events back to the client over a Redis Pub/Sub channel
scoped to that request. Every chat-service replica also runs a background
consumer in the same consumer group (see ``app.services.chat_worker``), so
if the replica that accepted the request dies before finishing, any
surviving replica reclaims the still-pending job (via ``XAUTOCLAIM`` after
an idle timeout) and finishes it — the assistant's reply still gets
computed and saved, even though the original HTTP connection is gone and
that specific client won't see it stream live.

This is at-least-once, not exactly-once: if a worker dies *after* calling
the LLM but *before* acknowledging the job, the next claimant reprocesses
it from scratch and a duplicate assistant message can result. That's judged
an acceptable trade for "never silently lose a response" given how rare a
mid-job crash actually is.
"""

from __future__ import annotations

import json
import socket
import uuid
from typing import Any

from llm_obs_shared.logging import get_logger
from redis.asyncio import Redis
from redis.exceptions import ResponseError

logger = get_logger(__name__)

_JOB_FIELD = "job"

JobEntry = tuple[str, dict[str, Any]]


class ChatJobQueue:
    def __init__(self, redis: Redis, *, stream: str, group: str) -> None:
        self._redis = redis
        self._stream = stream
        self._group = group
        self._consumer = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"

    async def ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(self._stream, self._group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def enqueue(self, job: dict[str, Any]) -> str:
        return await self._redis.xadd(self._stream, {_JOB_FIELD: json.dumps(job)})

    async def read_new(self, *, block_ms: int, count: int = 1) -> list[JobEntry]:
        resp = await self._redis.xreadgroup(
            self._group, self._consumer, {self._stream: ">"}, count=count, block=block_ms
        )
        return self._parse(resp)

    async def reclaim_orphaned(self, *, idle_ms: int, count: int = 10) -> list[JobEntry]:
        """Take over jobs whose original consumer has held them, unacked,
        for longer than ``idle_ms`` — the signature of a consumer that died
        mid-job rather than one still working."""

        _cursor, messages, _deleted = await self._redis.xautoclaim(
            self._stream, self._group, self._consumer, min_idle_time=idle_ms, start_id="0-0", count=count
        )
        return [(mid, json.loads(fields[_JOB_FIELD])) for mid, fields in messages if _JOB_FIELD in fields]

    def _parse(self, resp: Any) -> list[JobEntry]:
        out: list[JobEntry] = []
        for _stream_name, entries in resp or []:
            for mid, fields in entries:
                if _JOB_FIELD in fields:
                    out.append((mid, json.loads(fields[_JOB_FIELD])))
        return out

    async def ack(self, message_id: str) -> None:
        await self._redis.xack(self._stream, self._group, message_id)
