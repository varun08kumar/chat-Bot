"""Extract structured metadata from LiteLLM / OpenAI-style responses.

Everything here is defensive: the SDK must degrade gracefully when a provider
returns an unexpected shape rather than raising into the caller's request path.
"""

from __future__ import annotations

from typing import Any

from llm_obs_shared.schemas import TokenUsage


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Attribute- or key-style access that works for objects and dicts."""

    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def preview(text: str | None, max_chars: int) -> str:
    if not text:
        return ""
    text = str(text)
    return text if len(text) <= max_chars else text[:max_chars]


def extract_prompt_preview(messages: Any, max_chars: int) -> str:
    """Preview the most recent user message from an OpenAI-style message list."""

    if not messages:
        return ""
    try:
        for message in reversed(list(messages)):
            role = _get(message, "role")
            if role == "user":
                content = _get(message, "content")
                return preview(_flatten_content(content), max_chars)
        # Fall back to the last message regardless of role.
        return preview(_flatten_content(_get(messages[-1], "content")), max_chars)
    except Exception:  # noqa: BLE001
        return ""


def _flatten_content(content: Any) -> str:
    """Multi-modal content can be a list of parts; join the text parts."""

    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            text = _get(part, "text")
            if text:
                parts.append(str(text))
        return " ".join(parts)
    return str(content)


def extract_usage(response: Any) -> TokenUsage:
    usage = _get(response, "usage")
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        prompt_tokens=int(_get(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(_get(usage, "completion_tokens", 0) or 0),
        total_tokens=int(_get(usage, "total_tokens", 0) or 0),
    )


def extract_response_preview(response: Any, max_chars: int) -> str:
    choices = _get(response, "choices")
    if not choices:
        return ""
    try:
        first = choices[0]
        message = _get(first, "message")
        content = _get(message, "content") if message is not None else _get(first, "text")
        return preview(_flatten_content(content), max_chars)
    except Exception:  # noqa: BLE001
        return ""


def extract_model(response: Any, fallback: str | None) -> str:
    return str(_get(response, "model", fallback) or fallback or "unknown")


def extract_provider(response: Any, model: str, explicit: str | None) -> str:
    """Best-effort provider resolution.

    Prefers an explicit value, then LiteLLM's ``_hidden_params``, then the
    ``provider/model`` prefix convention (e.g. ``openai/gpt-4o``).
    """

    if explicit:
        return explicit
    hidden = _get(response, "_hidden_params") or {}
    provider = _get(hidden, "custom_llm_provider") or _get(hidden, "llm_provider")
    if provider:
        return str(provider)
    # LiteLLM's actual hidden-params field name for the requested model id
    # (retains the "provider/model" prefix even when `response.model` doesn't).
    litellm_model_name = _get(hidden, "litellm_model_name")
    if litellm_model_name and "/" in str(litellm_model_name):
        return str(litellm_model_name).split("/", 1)[0]
    if model and "/" in model:
        return model.split("/", 1)[0]
    return "unknown"


def extract_provider_metadata(response: Any) -> dict:
    """Capture non-sensitive provider response metadata."""

    metadata: dict[str, Any] = {}
    choices = _get(response, "choices") or []
    if choices:
        finish_reason = _get(choices[0], "finish_reason")
        if finish_reason is not None:
            metadata["finish_reason"] = finish_reason
    for field in ("id", "system_fingerprint", "created", "object"):
        value = _get(response, field)
        if value is not None:
            metadata[field] = value
    return metadata
