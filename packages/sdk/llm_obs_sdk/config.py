"""SDK configuration.

The SDK is configured once at application startup via :func:`configure_sdk`.
Everything is overridable through the environment so services need no code
changes between environments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class SdkConfig:
    """Runtime configuration for the observability SDK."""

    bootstrap_servers: str = field(default_factory=lambda: _env("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094"))
    client_id: str = field(default_factory=lambda: _env("SDK_KAFKA_CLIENT_ID", "llm-obs-sdk"))
    topic: str = field(default_factory=lambda: _env("SDK_INFERENCE_TOPIC", "inference.logs"))
    security_protocol: str = field(default_factory=lambda: _env("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"))

    #: Max events buffered in-memory before the oldest is dropped (back-pressure
    #: guard so logging can never exhaust memory or block inference).
    queue_max_size: int = field(default_factory=lambda: _env_int("SDK_QUEUE_MAX_SIZE", 10_000))
    #: Send retries per event before it is dropped (and counted as an error).
    send_max_retries: int = field(default_factory=lambda: _env_int("SDK_SEND_MAX_RETRIES", 3))
    #: Seconds to wait for the producer to flush on shutdown.
    flush_timeout_s: float = field(default_factory=lambda: float(_env("SDK_FLUSH_TIMEOUT_S", "5")))
    #: Characters of prompt/response kept as a preview.
    preview_chars: int = field(default_factory=lambda: _env_int("SDK_PREVIEW_CHARS", 200))
    #: When False the SDK becomes a no-op (useful for unit tests).
    enabled: bool = field(default_factory=lambda: _env_bool("SDK_ENABLED", True))
