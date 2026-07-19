"""Correlation-id propagation using :mod:`contextvars`.

A correlation id ties together every log line, Kafka event and DB row that
originates from a single inbound HTTP request. Because it lives in a
``ContextVar`` it survives across ``await`` boundaries within the same task
without having to be threaded through every function signature.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

#: Header used to accept/propagate a correlation id across service boundaries.
CORRELATION_ID_HEADER = "X-Correlation-ID"

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    """Return a fresh correlation id (a hex UUID4)."""

    return uuid.uuid4().hex


def set_correlation_id(value: str | None) -> str:
    """Set the correlation id for the current context, generating one if absent."""

    resolved = value or new_correlation_id()
    correlation_id_var.set(resolved)
    return resolved


def get_correlation_id() -> str | None:
    """Return the correlation id bound to the current context, if any."""

    return correlation_id_var.get()
