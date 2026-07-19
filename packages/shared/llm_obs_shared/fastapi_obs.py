"""Reusable FastAPI observability wiring shared by every service.

Adds the Prometheus middleware, a ``/metrics`` endpoint, and liveness /
readiness probes. FastAPI is imported lazily so the core ``shared`` package
stays free of a web-framework dependency.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from llm_obs_shared.asgi import PrometheusMiddleware
from llm_obs_shared.metrics import render_latest

#: A readiness check returns True when the dependency is healthy.
HealthCheck = Callable[[], Awaitable[bool]]


def install_observability(
    app,
    *,
    service_name: str,
    readiness_checks: dict[str, HealthCheck] | None = None,
) -> None:
    """Attach metrics middleware and health/metrics routes to a FastAPI app."""

    from fastapi import Response
    from fastapi.responses import JSONResponse

    app.add_middleware(PrometheusMiddleware)
    checks = readiness_checks or {}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:  # pragma: no cover - exercised via HTTP
        payload, content_type = render_latest()
        return Response(content=payload, media_type=content_type)

    @app.get("/health", include_in_schema=False)
    async def health() -> dict:
        """Liveness: the process is up and serving."""

        return {"status": "ok", "service": service_name}

    @app.get("/health/ready", include_in_schema=False)
    async def ready() -> JSONResponse:
        """Readiness: every declared dependency is reachable."""

        results: dict[str, bool] = {}
        for name, check in checks.items():
            try:
                results[name] = await check()
            except Exception:  # noqa: BLE001
                results[name] = False
        healthy = all(results.values()) if results else True
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={"status": "ready" if healthy else "unavailable", "checks": results},
        )
