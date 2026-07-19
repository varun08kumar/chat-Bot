"""Provider / model catalogue.

Adding a new provider is intentionally trivial: append an entry here and set the
corresponding API key env var. LiteLLM handles the actual routing, so no code
changes are needed elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelInfo:
    id: str  # LiteLLM model identifier, e.g. "gpt-4o-mini" or "claude-3-5-sonnet-latest"
    label: str
    context_window: int


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str
    api_key_setting: str  # attribute name on Settings holding the key
    models: list[ModelInfo] = field(default_factory=list)


# Registry of supported providers. OpenAI is enabled out of the box; the others
# light up automatically once their API key is configured.
PROVIDERS: dict[str, ProviderInfo] = {
    "openai": ProviderInfo(
        id="openai",
        label="OpenAI",
        api_key_setting="openai_api_key",
        models=[
            ModelInfo("gpt-4o-mini", "GPT-4o mini", 128_000),
            ModelInfo("gpt-4o", "GPT-4o", 128_000),
            ModelInfo("gpt-4.1-mini", "GPT-4.1 mini", 1_000_000),
        ],
    ),
    "anthropic": ProviderInfo(
        id="anthropic",
        label="Anthropic",
        api_key_setting="anthropic_api_key",
        models=[
            ModelInfo("claude-3-5-sonnet-latest", "Claude 3.5 Sonnet", 200_000),
            ModelInfo("claude-3-5-haiku-latest", "Claude 3.5 Haiku", 200_000),
        ],
    ),
    "groq": ProviderInfo(
        id="groq",
        label="Groq",
        api_key_setting="groq_api_key",
        models=[
            ModelInfo("groq/llama-3.3-70b-versatile", "Llama 3.3 70B", 128_000),
            ModelInfo("groq/llama-3.1-8b-instant", "Llama 3.1 8B", 128_000),
        ],
    ),
    "gemini": ProviderInfo(
        id="gemini",
        label="Google Gemini",
        api_key_setting="gemini_api_key",
        models=[
            ModelInfo("gemini/gemini-1.5-flash", "Gemini 1.5 Flash", 1_000_000),
            ModelInfo("gemini/gemini-1.5-pro", "Gemini 1.5 Pro", 2_000_000),
        ],
    ),
}


def provider_for_model(model: str) -> str:
    """Resolve the provider id for a given model id."""

    if "/" in model:
        prefix = model.split("/", 1)[0]
        if prefix in PROVIDERS:
            return prefix
    for provider in PROVIDERS.values():
        if any(m.id == model for m in provider.models):
            return provider.id
    return "openai"  # sensible default for bare OpenAI model names
