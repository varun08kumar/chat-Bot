"""LiteLLM-backed inference client with automatic observability.

The non-streaming path is instrumented purely by the ``@observe_llm``
decorator. The streaming path uses ``observe_stream`` so tokens and the response
preview are captured once the stream completes — the SDK still emits the same
event shape either way.

Both paths support one round of tool calling (currently just ``web_search``,
see ``app.services.web_search``): the model is offered the tool on its first
turn, and if — and only if — it decides to use it, we execute the tool and
make one follow-up call with the result appended (tools aren't offered again
on that follow-up, which bounds this at a single round trip). Models/providers
that don't support tool calling fall back to a plain completion transparently.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import litellm
from llm_obs_sdk import observe_llm, observe_stream
from llm_obs_shared.logging import get_logger

from app.config import Settings
from app.services.providers import PROVIDERS, provider_for_model
from app.services.web_search import WEB_SEARCH_TOOL, WebSearchError, format_results_for_model, web_search

logger = get_logger(__name__)

# Return typed exceptions instead of retries inside LiteLLM; we handle failures.
litellm.drop_params = True
litellm.suppress_debug_info = True

TOOLS = [WEB_SEARCH_TOOL]

# Groq (and other providers serving open-weight models) sometimes generates a
# tool call its own server can't parse — a transient per-attempt failure, not
# a sign the model lacks tool support. A fresh generation attempt often
# parses cleanly, but each attempt is a full extra round trip to the
# provider, so this is capped low: worth one retry, not several.
_TOOL_TRANSIENT_MARKERS = ("tool_use_failed",)
_TOOL_CALL_MAX_ATTEMPTS = 2

# Substrings meaning the model/provider genuinely doesn't support tool
# calling at all — no point retrying, fall back to a plain completion.
_TOOL_UNSUPPORTED_MARKERS = (
    "does not support tool",
    "does not support function calling",
    "tools is not supported",
    "tool choice is not supported",
    "invalid parameter: 'tools'",
)


class LLMError(Exception):
    """Raised when an inference call fails after provider-level handling."""


def _is_transient_tool_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _TOOL_TRANSIENT_MARKERS)


def _is_unsupported_tools_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _TOOL_UNSUPPORTED_MARKERS)


class LLMClient:
    """Wraps LiteLLM completion calls and applies API keys per provider."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _api_key_for(self, model: str) -> str | None:
        provider = PROVIDERS.get(provider_for_model(model))
        if provider is None:
            return None
        return getattr(self._settings, provider.api_key_setting, None)

    async def _run_tool_call(self, tool_call: Any) -> dict[str, Any]:
        """Execute a single (non-streaming-response) tool call, build the ``tool`` message."""

        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        query = args.get("query", "")
        content = await self._search(query)
        return {"role": "tool", "tool_call_id": tool_call.id, "content": content}

    async def _search(self, query: str) -> str:
        try:
            results = await web_search(
                query,
                base_url=self._settings.searxng_url,
                max_results=self._settings.web_search_max_results,
            )
            return format_results_for_model(results)
        except WebSearchError as exc:
            logger.warning("Web search failed", extra={"query": query, "error": str(exc)})
            return f"Search failed: {exc}"

    async def _complete_offering_tools(self, *, model: str, messages: list[dict[str, Any]]) -> Any:
        """A tools-enabled completion, retrying transient tool-parse failures
        and falling back to a plain (tools-off) completion if the model
        genuinely doesn't support tools or retries are exhausted."""

        last_exc: Exception | None = None
        for _ in range(_TOOL_CALL_MAX_ATTEMPTS):
            try:
                return await self._acompletion(
                    model=model, messages=messages, tools=TOOLS, tool_choice="auto", parallel_tool_calls=False
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if _is_transient_tool_error(exc):
                    continue
                if _is_unsupported_tools_error(exc):
                    break
                raise
        logger.info(
            "Falling back to a tools-off completion",
            extra={"model": model, "reason": str(last_exc)[:200] if last_exc else None},
        )
        return await self._acompletion(model=model, messages=messages)

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
        """Non-streaming completion. Returns (text, usage). Offers the web-search tool."""

        def usage_of(response: Any) -> dict[str, int]:
            usage = getattr(response, "usage", None)
            return {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(usage, "total_tokens", 0) or 0,
            }

        try:
            response = await self._complete_offering_tools(model=model, messages=messages)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(str(exc)) from exc

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)
        usage = usage_of(response)

        if tool_calls:
            tool_messages = [await self._run_tool_call(tc) for tc in tool_calls]
            follow_up_messages = [
                *messages,
                {"role": "assistant", "content": message.content or "", "tool_calls": tool_calls},
                *tool_messages,
            ]
            try:
                response = await self._acompletion(model=model, messages=follow_up_messages)
            except Exception as exc:  # noqa: BLE001
                raise LLMError(str(exc)) from exc
            follow_up_usage = usage_of(response)
            usage = {k: usage[k] + follow_up_usage[k] for k in usage}
            message = response.choices[0].message

        return message.content or "", usage

    async def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a completion, yielding events. Offers the web-search tool.

        Yields dicts of shape ``{"type": "token"|"tool_call"|"usage"}``. The SDK
        event is emitted automatically when the stream finishes (or errors).
        """

        provider = provider_for_model(model)
        async with observe_stream(
            provider=provider, model=model, messages=messages, endpoint="/chat/stream"
        ) as span:
            try:
                prompt_tokens = completion_tokens = 0
                pending_events: list[dict[str, Any]] = []

                async def run_pass(msgs: list[dict[str, Any]], *, with_tools: bool) -> tuple[str | None, list[dict[str, Any]]]:
                    """One streamed completion; appends token events to pending_events."""

                    nonlocal prompt_tokens, completion_tokens
                    kwargs: dict[str, Any] = {"stream": True, "stream_options": {"include_usage": True}}
                    if with_tools:
                        kwargs["tools"] = TOOLS
                        kwargs["tool_choice"] = "auto"
                        kwargs["parallel_tool_calls"] = False
                    resp = await litellm.acompletion(
                        model=model,
                        messages=msgs,
                        api_key=self._api_key_for(model),
                        timeout=self._settings.llm_timeout_s,
                        **kwargs,
                    )
                    finish_reason: str | None = None
                    tool_call_chunks: dict[int, dict[str, Any]] = {}
                    async for chunk in resp:
                        choices = getattr(chunk, "choices", None) or []
                        if choices:
                            delta = getattr(choices[0], "delta", None)
                            token = getattr(delta, "content", None) if delta else None
                            if token:
                                span.add_text(token)
                                pending_events.append({"type": "token", "content": token})
                            for d in (getattr(delta, "tool_calls", None) if delta else None) or []:
                                slot = tool_call_chunks.setdefault(d.index, {"id": None, "name": "", "arguments": ""})
                                if d.id:
                                    slot["id"] = d.id
                                if d.function and d.function.name:
                                    slot["name"] += d.function.name
                                if d.function and d.function.arguments:
                                    slot["arguments"] += d.function.arguments
                            fr = getattr(choices[0], "finish_reason", None)
                            if fr:
                                finish_reason = fr
                        usage = getattr(chunk, "usage", None)
                        if usage is not None:
                            prompt_tokens = getattr(usage, "prompt_tokens", prompt_tokens) or prompt_tokens
                            completion_tokens = getattr(usage, "completion_tokens", completion_tokens) or completion_tokens
                    return finish_reason, [tool_call_chunks[i] for i in sorted(tool_call_chunks)]

                finish_reason: str | None = None
                raw_tool_calls: list[dict[str, Any]] = []
                last_exc: Exception | None = None
                for _ in range(_TOOL_CALL_MAX_ATTEMPTS):
                    try:
                        finish_reason, raw_tool_calls = await run_pass(messages, with_tools=True)
                        last_exc = None
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                        pending_events.clear()
                        if _is_transient_tool_error(exc):
                            continue
                        if _is_unsupported_tools_error(exc):
                            break
                        raise
                if last_exc is not None:
                    logger.info(
                        "Falling back to a tools-off stream",
                        extra={"model": model, "reason": str(last_exc)[:200]},
                    )
                    finish_reason, raw_tool_calls = await run_pass(messages, with_tools=False)

                for ev in pending_events:
                    yield ev
                pending_events.clear()

                if finish_reason == "tool_calls" and raw_tool_calls:
                    tool_messages = []
                    for tc in raw_tool_calls:
                        try:
                            query = json.loads(tc["arguments"] or "{}").get("query", "")
                        except json.JSONDecodeError:
                            query = ""
                        yield {"type": "tool_call", "name": tc["name"] or "web_search", "query": query}
                        content = await self._search(query)
                        tool_messages.append({"role": "tool", "tool_call_id": tc["id"], "content": content})

                    assistant_tool_call_msg = {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {"name": tc["name"], "arguments": tc["arguments"]},
                            }
                            for tc in raw_tool_calls
                        ],
                    }
                    follow_up_messages = [*messages, assistant_tool_call_msg, *tool_messages]
                    # Tools aren't offered again — bounds this at one round trip.
                    finish_reason, _ = await run_pass(follow_up_messages, with_tools=False)
                    for ev in pending_events:
                        yield ev

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
