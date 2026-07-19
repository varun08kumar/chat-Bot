"""Framework-agnostic ASGI helpers for HTTP observability.

``PrometheusMiddleware`` is a pure-ASGI middleware (no Starlette dependency) so
it can wrap any ASGI app. It records request counts and latencies, and manages
the correlation-id lifecycle for each request.
"""

from __future__ import annotations

import re
import time
from typing import Awaitable, Callable

from llm_obs_shared.correlation import (
    CORRELATION_ID_HEADER,
    set_correlation_id,
)
from llm_obs_shared.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
)

Scope = dict
Receive = Callable[[], Awaitable[dict]]
Send = Callable[[dict], Awaitable[None]]

# Endpoints we never want to explode Prometheus label cardinality with.
_LOW_VALUE_PATHS = {"/metrics", "/health", "/health/ready", "/favicon.ico"}

# Collapse high-cardinality path segments (ids) into a placeholder so the
# ``path`` label stays bounded even without a framework route template.
_HEX_ID = re.compile(r"^[0-9a-fA-F]{16,}$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def normalize_path(path: str) -> str:
    segments = []
    for segment in path.split("/"):
        if segment.isdigit() or _HEX_ID.match(segment) or _UUID.match(segment):
            segments.append(":id")
        else:
            segments.append(segment)
    return "/".join(segments) or "/"


def _header_value(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


class PrometheusMiddleware:
    """Records HTTP metrics and binds a correlation id per request."""

    def __init__(self, app, *, route_template: Callable[[Scope], str] | None = None) -> None:
        self.app = app
        # Optional hook so frameworks can supply the matched route template
        # (e.g. ``/conversation/{id}``) instead of the raw path, keeping label
        # cardinality bounded.
        self._route_template = route_template

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = _header_value(scope, CORRELATION_ID_HEADER.lower().encode("latin-1"))
        correlation_id = set_correlation_id(incoming)

        method = scope.get("method", "GET")
        path = scope.get("path", "")
        label_path = self._label_path(scope, path)
        start = time.perf_counter()
        status_holder = {"code": 500}

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                headers = message.setdefault("headers", [])
                headers.append(
                    (CORRELATION_ID_HEADER.encode("latin-1"), correlation_id.encode("latin-1"))
                )
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            if path not in _LOW_VALUE_PATHS:
                HTTP_REQUESTS_TOTAL.labels(method, label_path, status_holder["code"]).inc()
                HTTP_REQUEST_DURATION_SECONDS.labels(method, label_path).observe(elapsed)

    def _label_path(self, scope: Scope, raw_path: str) -> str:
        if self._route_template is not None:
            template = self._route_template(scope)
            if template:
                return template
        return normalize_path(raw_path)
