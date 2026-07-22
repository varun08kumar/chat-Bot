"""Chat endpoints: POST /chat (SSE streaming or JSON) and provider discovery."""

from __future__ import annotations

import asyncio
import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from llm_obs_shared.logging import get_logger
from sse_starlette.sse import EventSourceResponse

from app.api.schemas import ChatRequest, ChatResponse, ProviderOut, TokenUsageOut
from app.config import Settings, get_settings
from app.dependencies import (
    Identity,
    RateLimiter,
    get_chat_service,
    get_identity,
    get_rate_limiter,
    verify_csrf,
)
from app.services.chat_service import ChatService, ConversationNotFound, MessageNotFound
from app.services.llm_client import LLMError
from app.services.providers import PROVIDERS

logger = get_logger(__name__)
router = APIRouter(tags=["chat"])


async def _enforce_rate_limit(limiter: RateLimiter, identity: Identity) -> None:
    allowed, remaining = await limiter.check(identity.user_id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please slow down.",
            headers={"Retry-After": "60", "X-RateLimit-Remaining": str(remaining)},
        )


@router.post("/chat", dependencies=[Depends(verify_csrf)])
async def chat(
    payload: ChatRequest,
    request: Request,
    identity: Identity = Depends(get_identity),
    service: ChatService = Depends(get_chat_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    """Send a message. Streams tokens over SSE by default; returns JSON otherwise."""

    await _enforce_rate_limit(limiter, identity)
    try:
        prepared = await service.prepare(
            user_id=identity.user_id,
            message=payload.message,
            conversation_id=payload.conversation_id,
            model=payload.model,
            edit_message_id=payload.edit_message_id,
        )
    except ConversationNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except MessageNotFound:
        raise HTTPException(status_code=404, detail="Message not found or not editable")

    if not payload.stream:
        started = time.perf_counter()
        try:
            result = await service.complete(
                prepared, user_id=identity.user_id, session_id=identity.session_id
            )
        except LLMError as exc:
            raise HTTPException(status_code=502, detail=f"Inference failed: {exc}")
        usage = result["usage"]
        return ChatResponse(
            conversation_id=prepared.conversation_id,
            request_id=prepared.request_id,
            user_message_id=prepared.user_message_id,
            message=result["content"],
            model=prepared.model,
            provider=prepared.provider,
            usage=TokenUsageOut(**usage),
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    async def event_generator():
        # The actual completion now runs in a background worker (see
        # ChatService.stream_via_queue), not inline in this request, so a
        # disconnect here can't rely on GeneratorExit to stop it — instead
        # explicitly flag the job cancelled so the worker stops consuming
        # tokens for it on its next check.
        async for event in service.stream_via_queue(
            prepared, user_id=identity.user_id, session_id=identity.session_id
        ):
            if await request.is_disconnected():
                logger.info("Client disconnected; cancelling stream", extra={
                    "conversation_id": prepared.conversation_id,
                })
                await service.request_cancel(prepared.request_id)
                break
            yield {"event": event["event"], "data": json.dumps(event["data"])}

    return EventSourceResponse(event_generator(), ping=15)


@router.post("/chat/{request_id}/cancel", dependencies=[Depends(verify_csrf)])
async def cancel_chat(
    request_id: str,
    identity: Identity = Depends(get_identity),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    """Explicit cancel signal, called the moment the user clicks Stop.

    The disconnect-based cancellation in ``event_generator`` below only fires
    once this route notices the SSE connection dropped — inferring that can
    lag well behind a fast provider's own generation speed, letting most of
    the response finish (and get persisted) before the implicit path ever
    catches up. Calling this directly closes that gap. ``request_id`` is an
    unguessable uuid4 hex only ever handed to the client that started this
    exact request (in its ``start`` event), so authentication alone is a
    sufficient guard — no separate ownership lookup is needed.
    """

    await service.request_cancel(request_id)
    return {"cancelled": True}


@router.post("/chat/dummy", response_model=ChatResponse)
async def chat_dummy(payload: ChatRequest) -> ChatResponse:
    """Load-testing only: a canned response after a fixed 10ms delay.

    Skips the real provider call, the database, and Kafka entirely, so a
    load test against this route measures the ASGI/HTTP layer's own
    concurrency ceiling on this machine, unconfounded by LLM provider rate
    limits, DB round-trips, or Kafka backpressure.
    """

    started = time.perf_counter()
    await asyncio.sleep(0.01)
    return ChatResponse(
        conversation_id=payload.conversation_id or "dummy",
        request_id=uuid.uuid4().hex,
        user_message_id=uuid.uuid4().hex,
        message="This is a simulated response for load testing.",
        model=payload.model or "dummy",
        provider="dummy",
        usage=TokenUsageOut(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
    )


@router.get("/providers", response_model=list[ProviderOut])
async def providers(settings: Settings = Depends(get_settings)) -> list[ProviderOut]:
    """List providers and models; a provider is 'enabled' when its key is set."""

    out: list[ProviderOut] = []
    for provider in PROVIDERS.values():
        enabled = bool(getattr(settings, provider.api_key_setting, None))
        out.append(
            ProviderOut(
                id=provider.id,
                label=provider.label,
                enabled=enabled,
                models=[{"id": m.id, "label": m.label, "context_window": m.context_window} for m in provider.models],
            )
        )
    return out
