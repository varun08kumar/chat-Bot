"""Ambient observation context.

The chat service binds the current session / conversation / user onto context
variables at request time; the ``@observe_llm`` decorator then reads them so
callers never have to pass identifiers down into the inference function.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

session_id_var: ContextVar[str | None] = ContextVar("obs_session_id", default=None)
conversation_id_var: ContextVar[str | None] = ContextVar("obs_conversation_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("obs_user_id", default=None)
endpoint_var: ContextVar[str | None] = ContextVar("obs_endpoint", default=None)
request_id_var: ContextVar[str | None] = ContextVar("obs_request_id", default=None)


@dataclass(frozen=True)
class ObservationContext:
    session_id: str | None
    conversation_id: str | None
    user_id: str | None
    endpoint: str | None
    request_id: str | None


def current_context() -> ObservationContext:
    return ObservationContext(
        session_id=session_id_var.get(),
        conversation_id=conversation_id_var.get(),
        user_id=user_id_var.get(),
        endpoint=endpoint_var.get(),
        request_id=request_id_var.get(),
    )


@contextmanager
def observation_context(
    *,
    session_id: str | None = None,
    conversation_id: str | None = None,
    user_id: str | None = None,
    endpoint: str | None = None,
    request_id: str | None = None,
) -> Iterator[None]:
    """Bind observation identifiers for the duration of the ``with`` block.

    ``request_id``, when supplied, lets the caller's externally-visible request
    id (e.g. the one returned in an API response) become the same id the SDK
    logs — without it, the decorator generates its own, and the two can never
    be correlated after the fact.
    """

    tokens = [
        session_id_var.set(session_id),
        conversation_id_var.set(conversation_id),
        user_id_var.set(user_id),
        endpoint_var.set(endpoint),
        request_id_var.set(request_id),
    ]
    variables = [session_id_var, conversation_id_var, user_id_var, endpoint_var, request_id_var]
    try:
        yield
    finally:
        # When this wraps an async generator (as chat streaming does), a
        # client disconnect delivers GeneratorExit from whatever asyncio
        # Context happens to be current at cancellation time — not
        # necessarily the one `.set()` ran in above. `.reset()` then raises
        # ValueError ("created in a different Context"). The Context this
        # was bound to is being torn down either way, so there's nothing to
        # leak by skipping a reset that can't apply — just swallow it rather
        # than let it surface as an unretrieved task exception.
        for var, token in zip(variables, tokens):
            try:
                var.reset(token)
            except ValueError:
                pass
