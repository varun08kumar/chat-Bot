"""Transform raw inference events into normalised, redacted processed events."""

from __future__ import annotations

import json

from llm_obs_shared.schemas import InferenceLogEvent, ProcessedLogEvent
from pydantic import ValidationError

from app.pii import PiiRedactor


class InvalidEventError(Exception):
    """Raised when a message cannot be parsed/validated (routed to the DLQ)."""


class EventProcessor:
    def __init__(self, redactor: PiiRedactor) -> None:
        self._redactor = redactor

    def process(self, raw: bytes) -> ProcessedLogEvent:
        """Parse, validate, redact and normalise a single raw message."""

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise InvalidEventError(f"malformed JSON: {exc}") from exc

        try:
            event = InferenceLogEvent.model_validate(data)
        except ValidationError as exc:
            raise InvalidEventError(f"schema validation failed: {exc.errors()}") from exc

        prompt_preview, p_changed = self._redactor.redact_text(event.prompt_preview)
        response_preview, r_changed = self._redactor.redact_text(event.response_preview)
        metadata, m_changed = self._redactor.redact_metadata(dict(event.provider_metadata or {}))
        pii_redacted = p_changed or r_changed or m_changed

        # Normalise the previews back onto a copy before flattening.
        event.prompt_preview = prompt_preview
        event.response_preview = response_preview

        processed = ProcessedLogEvent.from_inference(
            event,
            pii_redacted=pii_redacted,
            extra_metadata={
                **metadata,
                "ingested_by": "ingestion-service",
            },
        )
        # Normalise provider/model casing for consistent downstream grouping.
        processed.provider = (processed.provider or "unknown").strip().lower()
        processed.model = (processed.model or "unknown").strip()
        return processed
