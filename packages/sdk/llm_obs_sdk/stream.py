"""Streaming instrumentation helper.

Streaming responses can only be measured once the stream is fully consumed, so
the decorator alone cannot capture tokens/preview for SSE. ``observe_stream`` is
an async context manager the service uses to record the outcome of a streamed
completion and emit the same :class:`InferenceLogEvent` as the decorator.
"""

from __future__ import annotations

import time
from types import TracebackType
from typing import Any

from llm_obs_shared.correlation import get_correlation_id
from llm_obs_shared.metrics import LLM_ERRORS_TOTAL, LLM_LATENCY_MS, LLM_REQUESTS_TOTAL
from llm_obs_shared.schemas import InferenceLogEvent, InferenceStatus, TokenUsage

from llm_obs_sdk import extractor
from llm_obs_sdk.context import current_context
from llm_obs_sdk.runtime import get_config, get_producer


class observe_stream:
    """Record and emit an inference event for a streamed completion.

    Usage::

        async with observe_stream(provider="openai", model=model,
                                   messages=messages) as span:
            async for chunk in stream:
                span.add_text(chunk_text)
                yield chunk_text
            span.set_usage(prompt_tokens=..., completion_tokens=...)
    """

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        messages: Any = None,
        endpoint: str | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._messages = messages
        self._endpoint = endpoint
        self._config = get_config()
        self._started = 0.0
        self._buffer: list[str] = []
        self._usage = TokenUsage()
        self._status = InferenceStatus.SUCCESS
        self._error: str | None = None
        self._metadata: dict = {}

    def add_text(self, text: str | None) -> None:
        """Accumulate streamed text for the response preview (bounded)."""

        if not text:
            return
        # Only keep enough characters to build the preview; discard the rest.
        remaining = self._config.preview_chars - sum(len(part) for part in self._buffer)
        if remaining > 0:
            self._buffer.append(str(text)[:remaining])

    def set_usage(self, *, prompt_tokens: int = 0, completion_tokens: int = 0, total_tokens: int | None = None) -> None:
        total = total_tokens if total_tokens is not None else prompt_tokens + completion_tokens
        self._usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
        )

    def set_metadata(self, **metadata: Any) -> None:
        self._metadata.update({k: v for k, v in metadata.items() if v is not None})

    def mark_cancelled(self) -> None:
        self._status = InferenceStatus.CANCELLED

    async def __aenter__(self) -> "observe_stream":
        self._started = time.perf_counter()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if exc is not None and self._status is not InferenceStatus.CANCELLED:
            self._status = (
                InferenceStatus.TIMEOUT if isinstance(exc, TimeoutError) else InferenceStatus.ERROR
            )
            self._error = f"{type(exc).__name__}: {exc}"[:500]
        self._emit()
        # Do not suppress exceptions.
        return False

    def _emit(self) -> None:
        try:
            latency_ms = (time.perf_counter() - self._started) * 1000.0
            ctx = current_context()
            event_kwargs = dict(
                correlation_id=get_correlation_id(),
                session_id=ctx.session_id,
                conversation_id=ctx.conversation_id,
                user_id=ctx.user_id,
                provider=self._provider,
                model=self._model,
                endpoint=self._endpoint or ctx.endpoint,
            )
            if ctx.request_id:
                event_kwargs["request_id"] = ctx.request_id
            event = InferenceLogEvent(
                **event_kwargs,
                prompt_preview=extractor.extract_prompt_preview(self._messages, self._config.preview_chars),
                response_preview="".join(self._buffer)[: self._config.preview_chars],
                usage=self._usage,
                latency_ms=round(latency_ms, 3),
                status=self._status,
                error=self._error,
                provider_metadata=self._metadata,
            )
            LLM_REQUESTS_TOTAL.labels(self._provider, self._model, str(self._status)).inc()
            LLM_LATENCY_MS.labels(self._provider, self._model).observe(latency_ms)
            if self._status not in (InferenceStatus.SUCCESS, InferenceStatus.CANCELLED):
                LLM_ERRORS_TOTAL.labels(self._provider, self._model).inc()
            get_producer().emit(event)
        except Exception:  # noqa: BLE001
            pass
