"""LiteLLM-backed inference client with automatic observability.

The non-streaming path is instrumented purely by the ``@observe_llm``
decorator. The streaming path uses ``observe_stream`` so tokens and the response
preview are captured once the stream completes — the SDK still emits the same
event shape either way.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import litellm
from llm_obs_sdk import observe_llm, observe_stream
from llm_obs_shared.logging import get_logger

from app.config import Settings
from app.services.providers import PROVIDERS, provider_for_model

logger = get_logger(__name__)

# Return typed exceptions instead of retries inside LiteLLM; we handle failures.
litellm.drop_params = True
litellm.suppress_debug_info = True


class LLMError(Exception):
    """Raised when an inference call fails after provider-level handling."""


class LLMClient:
    """Wraps LiteLLM completion calls and applies API keys per provider."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _api_key_for(self, model: str) -> str | None:
        provider = PROVIDERS.get(provider_for_model(model))
        if provider is None:
            return None
        return getattr(self._settings, provider.api_key_setting, None)

    @observe_llm(endpoint="/chat")
    async def _acompletion(self, *, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        """Single, decorated call site so every completion is auto-instrumented."""

        return await litellm.acompletion(
            model=model,
            messages=messages,
            api_key=self._api_key_for(model),
            timeout=self._settings.llm_timeout_s,
            **kwargs,
        )

    async def complete(self, *, model: str, messages: list[dict[str, Any]]) -> tuple[str, dict]:
        """Non-streaming completion. Returns (text, usage)."""

        try:
            response = await self._acompletion(model=model, messages=messages)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(str(exc)) from exc
        content = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        usage_dict = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
        }
        return content, usage_dict

    async def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a completion, yielding events.

        Yields dicts of shape ``{"type": "token"|"usage"|"done", ...}``. The SDK
        event is emitted automatically when the stream finishes (or errors).
        """

        provider = provider_for_model(model)
        async with observe_stream(
            provider=provider, model=model, messages=messages, endpoint="/chat/stream"
        ) as span:
            try:
                stream = await litellm.acompletion(
                    model=model,
                    messages=messages,
                    api_key=self._api_key_for(model),
                    timeout=self._settings.llm_timeout_s,
                    stream=True,
                    stream_options={"include_usage": True},
                )
                prompt_tokens = completion_tokens = 0
                finish_reason: str | None = None
                async for chunk in stream:
                    choices = getattr(chunk, "choices", None) or []
                    if choices:
                        delta = getattr(choices[0], "delta", None)
                        token = getattr(delta, "content", None) if delta else None
                        if token:
                            span.add_text(token)
                            yield {"type": "token", "content": token}
                        fr = getattr(choices[0], "finish_reason", None)
                        if fr:
                            finish_reason = fr
                    usage = getattr(chunk, "usage", None)
                    if usage is not None:
                        prompt_tokens = getattr(usage, "prompt_tokens", prompt_tokens) or prompt_tokens
                        completion_tokens = getattr(usage, "completion_tokens", completion_tokens) or completion_tokens
                span.set_usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
                span.set_metadata(finish_reason=finish_reason)
                yield {
                    "type": "usage",
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                }
            except Exception as exc:  # noqa: BLE001
                logger.warning("Streaming completion failed", extra={"model": model, "error": str(exc)})
                raise LLMError(str(exc)) from exc
