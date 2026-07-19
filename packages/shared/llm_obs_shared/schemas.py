"""Event contracts that flow through the Kafka pipeline.

``InferenceLogEvent`` is produced by the SDK onto ``inference.logs``.
``ProcessedLogEvent`` is produced by the ingestion service onto
``processed.logs`` after validation, redaction and normalisation, and is what
the consumer service persists to PostgreSQL.

Both models are Pydantic v2 and are the single source of truth for the wire
format — services import them rather than hand-rolling dicts.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

#: Prompt / response previews are truncated to this many characters. Full
#: prompt and completion text is deliberately never carried on the event.
PREVIEW_MAX_CHARS = 200


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InferenceStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class TokenUsage(BaseModel):
    """Token accounting for a single inference call."""

    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class InferenceLogEvent(BaseModel):
    """Raw inference event emitted by the SDK's ``@observe_llm`` decorator."""

    model_config = ConfigDict(extra="ignore", use_enum_values=True)

    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    correlation_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    user_id: str | None = None

    provider: str
    model: str
    endpoint: str | None = None

    prompt_preview: str = ""
    response_preview: str = ""

    usage: TokenUsage = Field(default_factory=TokenUsage)

    latency_ms: float = 0.0
    status: InferenceStatus = InferenceStatus.SUCCESS
    error: str | None = None

    #: Provider-specific response metadata (finish reason, system fingerprint…).
    provider_metadata: dict = Field(default_factory=dict)

    timestamp: datetime = Field(default_factory=_utcnow)


class ProcessedLogEvent(BaseModel):
    """Normalised, redacted event ready for persistence.

    It is a superset of the raw event with ingestion bookkeeping fields added.
    """

    model_config = ConfigDict(extra="ignore", use_enum_values=True)

    request_id: str
    correlation_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    user_id: str | None = None

    provider: str
    model: str
    endpoint: str | None = None

    prompt_preview: str = ""
    response_preview: str = ""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    latency_ms: float = 0.0
    status: InferenceStatus = InferenceStatus.SUCCESS
    error: str | None = None

    metadata: dict = Field(default_factory=dict)

    timestamp: datetime = Field(default_factory=_utcnow)
    ingested_at: datetime = Field(default_factory=_utcnow)
    #: Whether any field was altered by PII redaction.
    pii_redacted: bool = False

    @classmethod
    def from_inference(
        cls,
        event: "InferenceLogEvent",
        *,
        pii_redacted: bool = False,
        extra_metadata: dict | None = None,
    ) -> "ProcessedLogEvent":
        """Build a processed event from a raw one, flattening token usage."""

        usage = event.usage if isinstance(event.usage, TokenUsage) else TokenUsage(**(event.usage or {}))
        metadata = dict(event.provider_metadata or {})
        if extra_metadata:
            metadata.update(extra_metadata)
        return cls(
            request_id=event.request_id,
            correlation_id=event.correlation_id,
            session_id=event.session_id,
            conversation_id=event.conversation_id,
            user_id=event.user_id,
            provider=event.provider,
            model=event.model,
            endpoint=event.endpoint,
            prompt_preview=event.prompt_preview,
            response_preview=event.response_preview,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            latency_ms=event.latency_ms,
            status=event.status,
            error=event.error,
            metadata=metadata,
            timestamp=event.timestamp,
            pii_redacted=pii_redacted,
        )
