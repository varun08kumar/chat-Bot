"""PII redaction.

Applied to prompt/response previews and stringy metadata values before events
are persisted. The goal is defence-in-depth: previews are already truncated to
200 chars by the SDK, and this strips common direct identifiers on top.
"""

from __future__ import annotations

import re
from typing import Any

# Ordered so more specific patterns run before broader ones.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("[REDACTED_EMAIL]", re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")),
    ("[REDACTED_CARD]", re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
    ("[REDACTED_SSN]", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("[REDACTED_API_KEY]", re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9]{16,}\b")),
    ("[REDACTED_IP]", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    (
        "[REDACTED_PHONE]",
        re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\w)"),
    ),
]


class PiiRedactor:
    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled

    def redact_text(self, text: str | None) -> tuple[str, bool]:
        """Return (redacted_text, changed)."""

        if not text or not self._enabled:
            return text or "", False
        redacted = text
        for replacement, pattern in _PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        return redacted, redacted != text

    def redact_metadata(self, metadata: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        if not self._enabled or not metadata:
            return metadata, False
        changed = False
        cleaned: dict[str, Any] = {}
        for key, value in metadata.items():
            if isinstance(value, str):
                new_value, did = self.redact_text(value)
                cleaned[key] = new_value
                changed = changed or did
            else:
                cleaned[key] = value
        return cleaned, changed
