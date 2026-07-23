"""Chat orchestration: conversation state + inference + streaming.

This is the service layer. It coordinates repositories, the cache and the LLM
client but contains no framework or SQL details itself.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from llm_obs_sdk import observation_context
from llm_obs_shared.logging import get_logger
from llm_obs_shared.db.session import Database
from redis.asyncio import Redis

from app.config import Settings
from app.repositories.conversation_repository import (
    ConversationRepository,
    MessageRepository,
)
from app.services.cache import ConversationCache
from app.services.image_gen import ImageGenError, generate_image
from app.services.job_queue import ChatJobQueue
from app.services.llm_client import LLMClient, LLMError
from app.services.providers import provider_for_model
from app.services.web_search import WebSearchError, fetch_first_working_image, image_search

logger = get_logger(__name__)


def _event_channel(request_id: str) -> str:
    return f"chat:events:{request_id}"


def _cancel_key(request_id: str) -> str:
    return f"chat:cancel:{request_id}"


def _partial_key(request_id: str) -> str:
    return f"chat:partial:{request_id}"


def _system_prompt() -> str:
    # Regenerated per-request (not a module constant) so "today" is always
    # actually today — the model otherwise has no grounded reference for it
    # and either trusts a stale training cutoff or infers one from whatever
    # date happens to appear in search results.
    today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
    return (
        f"You are a helpful, concise assistant. Today's date is {today} (UTC). "
        "You have a web_search tool — use it only for things that can change "
        "in the real world after your training cutoff: live scores, prices, "
        "schedules, news, releases, or similar current-events facts, "
        "especially when the question says 'today', 'latest', 'current', or "
        "names a specific recent date. Never tell the user you lack "
        "real-time access without having searched first for that kind of "
        "question. "
        "Do NOT search for math, unit conversions, definitions, general "
        "knowledge, coding help, or anything else you can already answer "
        "correctly and completely on your own — searching for those only "
        "adds delay for no benefit. "
        "Judge each new message on its own wording — do not assume it "
        "continues an earlier unrelated topic (e.g. a sports score "
        "discussed previously in this conversation) unless it actually "
        "references that topic. A message that is only numbers and math "
        "operators (like '3+2' or 'current 3+2') is always a math "
        "question, regardless of what else was discussed earlier. "
        "You do not know the user's location or timezone, and must never "
        "guess one — not from their IP, and not by inferring it from an "
        "unrelated entity mentioned earlier in the conversation (e.g. "
        "asking for 'the time' after discussing an England cricket match "
        "does not mean the user is in the UK). If a question depends on "
        "location or timezone and none was given, ask which one they "
        "mean instead of assuming. "
        "Search results can span many different dates for similar events "
        "(e.g. matches or releases from different years) — check each "
        "result's date against today's real date above before treating it "
        "as current, and say so plainly if the results are ambiguous or "
        "don't clearly match what was asked, rather than presenting a "
        "mismatched result as if it were the answer."
    )


class ConversationNotFound(Exception):
    pass


class MessageNotFound(Exception):
    pass


@dataclass
class PreparedChat:
    conversation_id: str
    request_id: str
    model: str
    provider: str
    messages: list[dict[str, Any]]
    is_new: bool
    user_message_id: str


class ChatService:
    def __init__(
        self,
        *,
        db: Database,
        cache: ConversationCache,
        llm: LLMClient,
        settings: Settings,
        redis: Redis,
        job_queue: ChatJobQueue,
    ) -> None:
        self._db = db
        self._cache = cache
        self._llm = llm
        self._settings = settings
        self._redis = redis
        self._job_queue = job_queue

    async def _load_history(
        self, repo: MessageRepository, conversation_id: str
    ) -> list[dict[str, Any]]:
        cached = await self._cache.get_messages(conversation_id)
        if cached is not None:
            return cached
        messages = await repo.history(conversation_id, limit=self._settings.max_history_messages)
        history = [{"role": m.role, "content": m.content} for m in messages]
        await self._cache.set_messages(conversation_id, history)
        return history

    async def prepare(
        self,
        *,
        user_id: str,
        message: str,
        conversation_id: str | None,
        model: str | None,
        edit_message_id: str | None = None,
    ) -> PreparedChat:
        """Resolve conversation, persist the user turn, and assemble the prompt.

        If ``edit_message_id`` is set, that message (which must be an existing
        ``user`` turn in this conversation) and everything after it — including
        whatever the model replied — is deleted first, and ``message`` is
        inserted as its replacement. The rest of the flow is identical to a
        normal turn: the model sees only history up to the edit point.
        """

        model = model or self._settings.default_model
        provider = provider_for_model(model)
        request_id = uuid.uuid4().hex

        async with self._db.session() as session:
            conv_repo = ConversationRepository(session)
            msg_repo = MessageRepository(session)

            is_new = False
            if conversation_id:
                conversation = await conv_repo.get(conversation_id, user_id=user_id)
                if conversation is None:
                    raise ConversationNotFound(conversation_id)
            else:
                if edit_message_id:
                    raise ConversationNotFound(conversation_id)
                title = _derive_title(message)
                conversation = await conv_repo.create(user_id=user_id, title=title)
                conversation_id = conversation.id
                is_new = True

            if edit_message_id:
                target = await msg_repo.get(edit_message_id, conversation_id=conversation_id)
                if target is None or target.role != "user":
                    raise MessageNotFound(edit_message_id)
                await msg_repo.delete_from(conversation_id, edit_message_id)
                # The cache may still hold messages we just deleted; drop it
                # so _load_history below re-reads the truncated history from
                # the DB instead of serving the stale cached tail.
                await self._cache.invalidate(conversation_id)

            history = [] if is_new else await self._load_history(msg_repo, conversation_id)
            user_message = await msg_repo.add(conversation_id=conversation_id, role="user", content=message)
            await conv_repo.touch(conversation_id)

        prompt_messages = (
            [{"role": "system", "content": _system_prompt()}]
            + history
            + [{"role": "user", "content": message}]
        )
        # Refresh cache with the appended user message.
        await self._cache.set_messages(conversation_id, history + [{"role": "user", "content": message}])

        return PreparedChat(
            conversation_id=conversation_id,
            request_id=request_id,
            model=model,
            provider=provider,
            messages=prompt_messages,
            is_new=is_new,
            user_message_id=user_message.id,
        )

    async def _persist_assistant(self, conversation_id: str, content: str) -> None:
        async with self._db.session() as session:
            msg_repo = MessageRepository(session)
            conv_repo = ConversationRepository(session)
            await msg_repo.add(conversation_id=conversation_id, role="assistant", content=content)
            await conv_repo.touch(conversation_id)
        await self._cache.invalidate(conversation_id)

    async def complete(self, prepared: PreparedChat, *, user_id: str, session_id: str) -> dict[str, Any]:
        """Non-streaming completion."""

        with observation_context(
            session_id=session_id,
            conversation_id=prepared.conversation_id,
            user_id=user_id,
            endpoint="/chat",
            request_id=prepared.request_id,
        ):
            content, usage = await self._llm.complete(model=prepared.model, messages=prepared.messages)
        await self._persist_assistant(prepared.conversation_id, content)
        return {"content": content, "usage": usage}

    async def stream(
        self, prepared: PreparedChat, *, user_id: str, session_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a completion as semantic events; persists the final message.

        Client cancellation propagates as ``GeneratorExit``/``CancelledError``;
        we still persist whatever was generated so the conversation stays
        consistent, and the SDK records the call as cancelled.
        """

        collected: list[str] = []
        usage: dict[str, Any] = {}
        errored = False
        yield {"event": "start", "data": {
            "conversation_id": prepared.conversation_id,
            "request_id": prepared.request_id,
            "user_message_id": prepared.user_message_id,
            "model": prepared.model,
            "provider": prepared.provider,
        }}
        try:
            with observation_context(
                session_id=session_id,
                conversation_id=prepared.conversation_id,
                user_id=user_id,
                endpoint="/chat/stream",
                request_id=prepared.request_id,
            ):
                async for event in self._llm.stream(model=prepared.model, messages=prepared.messages):
                    if event["type"] == "token":
                        collected.append(event["content"])
                        # Durable outside this process's memory: if this
                        # worker crashes before the finally block below runs,
                        # whichever worker reclaims the orphaned job (see
                        # ChatService.recover_or_run) can persist exactly
                        # what was already streamed to the user, instead of
                        # silently generating a different answer from scratch.
                        async with self._redis.pipeline(transaction=False) as pipe:
                            pipe.append(_partial_key(prepared.request_id), event["content"])
                            pipe.expire(_partial_key(prepared.request_id), self._settings.chat_partial_ttl_s)
                            await pipe.execute()
                        yield {"event": "token", "data": {"content": event["content"]}}
                    elif event["type"] == "usage":
                        usage = {k: v for k, v in event.items() if k != "type"}
                        yield {"event": "usage", "data": usage}
                    elif event["type"] == "tool_call":
                        yield {"event": "tool_call", "data": {"name": event["name"], "query": event["query"]}}
                    # Cancellation now has to be polled rather than relying
                    # solely on GeneratorExit: when this runs inside the
                    # background worker (see stream_via_queue/run_and_publish
                    # below), there's no live HTTP request/generator to be
                    # torn down when the client hits Stop, so the request
                    # handler instead sets a short-lived Redis flag and we
                    # check it here — same "stop early, keep what we have"
                    # behavior as the old request.is_disconnected() check.
                    if await self._redis.exists(_cancel_key(prepared.request_id)):
                        logger.info("Chat job cancelled", extra={"request_id": prepared.request_id})
                        break
        except LLMError as exc:
            errored = True
            yield {"event": "error", "data": {"message": str(exc)}}
        finally:
            text = "".join(collected)
            if text:
                await self._persist_assistant(prepared.conversation_id, text)
            # This process is finishing the job itself (whether cleanly,
            # cancelled, or errored) — nothing will need to recover it, so
            # the partial buffer no longer needs to survive a crash.
            await self._redis.delete(_partial_key(prepared.request_id))
        if not errored:
            yield {"event": "done", "data": {
                "conversation_id": prepared.conversation_id,
                "usage": usage,
            }}

    async def stream_via_queue(
        self, prepared: PreparedChat, *, user_id: str, session_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """HTTP-facing entry point for streaming: enqueue the actual work as
        a durable job (see job_queue.py) rather than calling the provider
        inline, then relay events back over Redis Pub/Sub as they're
        published by whichever replica's worker ends up processing it
        (almost always this same process, moments later — the queue hop
        adds negligible latency in the common case, and buys durability in
        the uncommon one)."""

        channel = _event_channel(prepared.request_id)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            # Subscribe *before* enqueueing: Pub/Sub has no backlog, so a
            # worker that reacts fast enough could otherwise publish the
            # "start" event (and even the first tokens) before we're
            # listening for them.
            job = {
                "conversation_id": prepared.conversation_id,
                "request_id": prepared.request_id,
                "user_message_id": prepared.user_message_id,
                "model": prepared.model,
                "provider": prepared.provider,
                "messages": prepared.messages,
                "user_id": user_id,
                "session_id": session_id,
            }
            await self._job_queue.enqueue(job)

            deadline = time.monotonic() + self._settings.chat_job_relay_timeout_s
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    yield {"event": "error", "data": {"message": "Timed out waiting for a response."}}
                    return
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=min(remaining, 1.0))
                if message is None:
                    continue
                event = json.loads(message["data"])
                yield event
                if event["event"] in ("done", "error"):
                    return
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    async def run_and_publish(self, prepared: PreparedChat, *, user_id: str, session_id: str) -> None:
        """Worker-side counterpart to stream_via_queue: run the real
        completion (persisting as it goes, same as ``stream``) and publish
        each event for any relay currently listening. Runs to completion —
        and still persists — even if nobody ends up listening at all,
        which is the entire point: the client's HTTP connection dying
        doesn't stop this."""

        channel = _event_channel(prepared.request_id)
        async for event in self.stream(prepared, user_id=user_id, session_id=session_id):
            await self._redis.publish(channel, json.dumps(event))

    async def recover_or_run(self, prepared: PreparedChat, *, user_id: str, session_id: str) -> None:
        """Entry point for the worker loop — covers both fresh jobs and ones
        reclaimed from a crashed worker (see chat_worker.py's
        reclaim_orphaned/XAUTOCLAIM).

        A fresh job has no partial buffer yet (nothing has streamed), so this
        just runs normally. A reclaimed job may have one: its original worker
        died mid-stream, after showing the user some tokens but before its own
        ``stream()`` call reached the ``finally`` block that persists and
        cleans up. In that case we persist exactly what was already shown
        instead of silently generating a different answer from scratch —
        the model is never called again here. Whether to get the rest of the
        answer becomes the user's own choice, via the existing Continue
        button, once the truncated message is just sitting in history like
        any other turn.
        """

        partial = await self._redis.get(_partial_key(prepared.request_id))
        if partial:
            await self._persist_assistant(prepared.conversation_id, partial)
            await self._redis.delete(_partial_key(prepared.request_id))
            logger.warning(
                "Recovered a crashed worker's partial response",
                extra={"request_id": prepared.request_id, "chars_recovered": len(partial)},
            )
            return
        await self.run_and_publish(prepared, user_id=user_id, session_id=session_id)

    async def generate_image(
        self, *, user_id: str, conversation_id: str | None, prompt: str
    ) -> dict[str, Any]:
        """Generate an image via Pollinations.ai and persist it as a turn.

        The image is stored as a markdown image tag (a ``data:`` URI) in an
        assistant message's ``content`` — the frontend already renders
        assistant content through ``react-markdown``, so this needs no new
        message type or rendering path, just a normal message the image
        happens to be embedded in.
        """

        async with self._db.session() as session:
            conv_repo = ConversationRepository(session)
            msg_repo = MessageRepository(session)

            is_new = False
            if conversation_id:
                conversation = await conv_repo.get(conversation_id, user_id=user_id)
                if conversation is None:
                    raise ConversationNotFound(conversation_id)
            else:
                conversation = await conv_repo.create(user_id=user_id, title=_derive_title(prompt))
                conversation_id = conversation.id
                is_new = True

            user_message = await msg_repo.add(conversation_id=conversation_id, role="user", content=prompt)
            await conv_repo.touch(conversation_id)

        data_uri = await generate_image(prompt)
        content = f"![{prompt}]({data_uri})"

        async with self._db.session() as session:
            msg_repo = MessageRepository(session)
            conv_repo = ConversationRepository(session)
            assistant_message = await msg_repo.add(conversation_id=conversation_id, role="assistant", content=content)
            await conv_repo.touch(conversation_id)
        await self._cache.invalidate(conversation_id)

        return {
            "conversation_id": conversation_id,
            "is_new": is_new,
            "user_message": {
                "id": user_message.id,
                "role": "user",
                "content": prompt,
                "created_at": user_message.created_at,
            },
            "assistant_message": {
                "id": assistant_message.id,
                "role": "assistant",
                "content": content,
                "created_at": assistant_message.created_at,
            },
        }

    async def search_image(
        self, *, user_id: str, conversation_id: str | None, query: str
    ) -> dict[str, Any]:
        """Find a real photo on the web (via SearXNG's image category) and
        persist it as a turn — distinct from ``generate_image``, which
        fabricates a new image rather than fetching an existing one.
        """

        results = await image_search(query, base_url=self._settings.searxng_url, max_results=10)
        if not results:
            raise WebSearchError(f"No image results found for '{query}'.")
        found = await fetch_first_working_image(results)
        if found is None:
            raise WebSearchError(f"Found results for '{query}', but none of their images could be loaded.")
        top, image_bytes, content_type = found

        async with self._db.session() as session:
            conv_repo = ConversationRepository(session)
            msg_repo = MessageRepository(session)

            is_new = False
            if conversation_id:
                conversation = await conv_repo.get(conversation_id, user_id=user_id)
                if conversation is None:
                    raise ConversationNotFound(conversation_id)
            else:
                conversation = await conv_repo.create(user_id=user_id, title=_derive_title(query))
                conversation_id = conversation.id
                is_new = True

            user_message = await msg_repo.add(conversation_id=conversation_id, role="user", content=query)
            await conv_repo.touch(conversation_id)

        # Embedded as a data: URI - not the original img_src - so the
        # browser never makes a cross-origin request to the source site at
        # all, sidestepping any hotlink protection that would otherwise
        # block the embed even though our own server-side fetch succeeded.
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_uri = f"data:{content_type};base64,{b64}"
        content = f"![{top['title'] or query}]({data_uri})\n\n[Source]({top['page_url']})"

        async with self._db.session() as session:
            msg_repo = MessageRepository(session)
            conv_repo = ConversationRepository(session)
            assistant_message = await msg_repo.add(conversation_id=conversation_id, role="assistant", content=content)
            await conv_repo.touch(conversation_id)
        await self._cache.invalidate(conversation_id)

        return {
            "conversation_id": conversation_id,
            "is_new": is_new,
            "user_message": {
                "id": user_message.id,
                "role": "user",
                "content": query,
                "created_at": user_message.created_at,
            },
            "assistant_message": {
                "id": assistant_message.id,
                "role": "assistant",
                "content": content,
                "created_at": assistant_message.created_at,
            },
        }

    async def request_cancel(self, request_id: str) -> None:
        """Flag a request as cancelled so the worker (which isn't driven by
        the HTTP request/generator anymore, and so can't rely on
        GeneratorExit) stops consuming tokens for it on its next check."""

        await self._redis.set(_cancel_key(request_id), "1", ex=300)


def _derive_title(message: str) -> str:
    title = " ".join(message.strip().split())
    return (title[:60] + "…") if len(title) > 60 else (title or "New conversation")
