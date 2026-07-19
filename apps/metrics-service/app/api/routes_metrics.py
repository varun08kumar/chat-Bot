"""Dashboard metric endpoints.

Every endpoint accepts an optional ``window`` query parameter (15m, 1h, 6h, 24h,
7d, 30d). Responses are plain JSON so the frontend can chart them directly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_repository
from app.repository import MetricsRepository
from app.window import available_windows, resolve_window

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _window(window: str | None = Query(default=None, description="15m|1h|6h|24h|7d|30d")):
    return resolve_window(window)


@router.get("/providers")
async def providers(win=Depends(_window), repo: MetricsRepository = Depends(get_repository)):
    return {"window": win.key, "providers": await repo.providers(win)}


@router.get("/models")
async def models(win=Depends(_window), repo: MetricsRepository = Depends(get_repository)):
    return {"window": win.key, "models": await repo.models(win)}


@router.get("/latency")
async def latency(win=Depends(_window), repo: MetricsRepository = Depends(get_repository)):
    return {
        "window": win.key,
        "summary": await repo.latency_summary(win),
        "series": await repo.latency_series(win),
    }


@router.get("/throughput")
async def throughput(win=Depends(_window), repo: MetricsRepository = Depends(get_repository)):
    return {"window": win.key, "series": await repo.throughput_series(win)}


@router.get("/errors")
async def errors(win=Depends(_window), repo: MetricsRepository = Depends(get_repository)):
    return {
        "window": win.key,
        "series": await repo.errors_series(win),
        "recent": await repo.recent_errors(win),
    }


@router.get("/tokens")
async def tokens(win=Depends(_window), repo: MetricsRepository = Depends(get_repository)):
    return {"window": win.key, **await repo.tokens(win)}


@router.get("/dashboard")
async def dashboard(win=Depends(_window), repo: MetricsRepository = Depends(get_repository)):
    """One-shot payload powering the main dashboard page."""

    return {
        "window": win.key,
        "available_windows": available_windows(),
        "summary": await repo.summary(win),
        "latency": {
            "summary": await repo.latency_summary(win),
            "series": await repo.latency_series(win),
        },
        "throughput": await repo.throughput_series(win),
        "errors": await repo.errors_series(win),
        "providers": await repo.providers(win),
        "models": await repo.models(win),
        "tokens": await repo.tokens(win),
    }
