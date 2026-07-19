"""The ``@observe_llm`` decorator — automatic inference instrumentation.

Wrapping an async inference function is all a developer needs to do::

    @observe_llm(endpoint="/chat")
    async def complete(*, messages, model):
        return await litellm.acompletion(model=model, messages=messages)

On every call the decorator captures latency, tokens, previews, provider/model,
status and errors, then emits an :class:`InferenceLogEvent` asynchronously. It
never changes the function's return value and never blocks on logging.
"""

from __future__ import annotations

import functools
import inspect
import time
from typing import Any, Callable, TypeVar

from llm_obs_shared.correlation import get_correlation_id
from llm_obs_shared.metrics import LLM_ERRORS_TOTAL, LLM_LATENCY_MS, LLM_REQUESTS_TOTAL
from llm_obs_shared.schemas import InferenceLogEvent, InferenceStatus

from llm_obs_sdk import extractor
from llm_obs_sdk.context import current_context
from llm_obs_sdk.runtime import get_config, get_producer

F = TypeVar("F", bound=Callable[..., Any])


def observe_llm(
    _fn: F | None = None,
    *,
    provider: str | None = None,
    endpoint: str | None = None,
) -> Any:
    """Instrument an (async) LLM inference function.

    Parameters
    ----------
    provider:
        Optional explicit provider name. When omitted it is inferred from the
        response metadata or the ``provider/model`` naming convention.
    endpoint:
        Logical endpoint label (defaults to the ambient observation context).
    """

    def decorate(fn: F) -> F:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                started = time.perf_counter()
                status = InferenceStatus.SUCCESS
                error: str | None = None
                response: Any = None
                try:
                    response = await fn(*args, **kwargs)
                    return response
                except TimeoutError as exc:
                    status, error = InferenceStatus.TIMEOUT, _err(exc)
                    raise
                except Exception as exc:  # noqa: BLE001
                    status, error = InferenceStatus.ERROR, _err(exc)
                    raise
                finally:
                    _record(
                        started=started,
                        status=status,
                        error=error,
                        response=response,
                        bound=_safe_bind(fn, args, kwargs),
                        explicit_provider=provider,
                        explicit_endpoint=endpoint,
                    )

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            status = InferenceStatus.SUCCESS
            error: str | None = None
            response: Any = None
            try:
                response = fn(*args, **kwargs)
                return response
            except TimeoutError as exc:
                status, error = InferenceStatus.TIMEOUT, _err(exc)
                raise
            except Exception as exc:  # noqa: BLE001
                status, error = InferenceStatus.ERROR, _err(exc)
                raise
            finally:
                _record(
                    started=started,
                    status=status,
                    error=error,
                    response=response,
                    bound=_safe_bind(fn, args, kwargs),
                    explicit_provider=provider,
                    explicit_endpoint=endpoint,
                )

        return sync_wrapper  # type: ignore[return-value]

    # Support both @observe_llm and @observe_llm(...)
    if _fn is not None and callable(_fn):
        return decorate(_fn)
    return decorate


def _err(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]


def _safe_bind(fn: Callable, args: tuple, kwargs: dict) -> dict:
    """Bind call arguments to parameter names, tolerating partial signatures."""

    try:
        sig = inspect.signature(fn)
        bound = sig.bind_partial(*args, **kwargs)
        bound.apply_defaults()
        return dict(bound.arguments)
    except Exception:  # noqa: BLE001
        return dict(kwargs)


def _record(
    *,
    started: float,
    status: InferenceStatus,
    error: str | None,
    response: Any,
    bound: dict,
    explicit_provider: str | None,
    explicit_endpoint: str | None,
) -> None:
    """Build and emit the inference event. Must never raise."""

    try:
        config = get_config()
        latency_ms = (time.perf_counter() - started) * 1000.0

        # The caller-supplied model (e.g. "groq/llama-3.3-70b-versatile") is
        # authoritative — some providers echo back `response.model` without
        # the provider prefix, which would otherwise silently discard it.
        model = bound.get("model") or extractor.extract_model(response, None)
        provider = extractor.extract_provider(response, model, explicit_provider)

        ctx = current_context()
        event_kwargs = dict(
            correlation_id=get_correlation_id(),
            session_id=ctx.session_id,
            conversation_id=ctx.conversation_id,
            user_id=ctx.user_id,
            provider=provider,
            model=model,
            endpoint=explicit_endpoint or ctx.endpoint,
        )
        if ctx.request_id:
            event_kwargs["request_id"] = ctx.request_id
        event = InferenceLogEvent(
            **event_kwargs,
            prompt_preview=extractor.extract_prompt_preview(bound.get("messages"), config.preview_chars),
            response_preview=extractor.extract_response_preview(response, config.preview_chars),
            usage=extractor.extract_usage(response),
            latency_ms=round(latency_ms, 3),
            status=status,
            error=error,
            provider_metadata=extractor.extract_provider_metadata(response),
        )

        # Prometheus (synchronous, cheap, in-process).
        LLM_REQUESTS_TOTAL.labels(provider, model, str(status)).inc()
        LLM_LATENCY_MS.labels(provider, model).observe(latency_ms)
        if status is not InferenceStatus.SUCCESS:
            LLM_ERRORS_TOTAL.labels(provider, model).inc()

        # Kafka (asynchronous, fire-and-forget).
        get_producer().emit(event)
    except Exception:  # noqa: BLE001 - instrumentation must never break inference
        pass
