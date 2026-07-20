"""Dashboard metric endpoints — scoped to the requesting user.

Every endpoint accepts an optional ``window`` query parameter (15m, 1h, 6h, 24h,
7d, 30d) and requires the same access-token cookie chat-service issues. Each
user sees only their own usage; the all-users breakdown lives in Grafana's
"Per-User Usage" dashboard instead, which is behind Grafana's own separate
login rather than any individual account's session.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.dependencies import Identity, get_identity, get_repository
from app.repository import MetricsRepository
from app.window import available_windows, resolve_window

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _window(window: str | None = Query(default=None, description="15m|1h|6h|24h|7d|30d")):
    return resolve_window(window)


@router.get("/providers")
async def providers(
    win=Depends(_window),
    repo: MetricsRepository = Depends(get_repository),
    identity: Identity = Depends(get_identity),
):
    return {"window": win.key, "providers": await repo.providers(win, identity.user_id)}


@router.get("/models")
async def models(
    win=Depends(_window),
    repo: MetricsRepository = Depends(get_repository),
    identity: Identity = Depends(get_identity),
):
    return {"window": win.key, "models": await repo.models(win, identity.user_id)}


@router.get("/latency")
async def latency(
    win=Depends(_window),
    repo: MetricsRepository = Depends(get_repository),
    identity: Identity = Depends(get_identity),
):
    return {
        "window": win.key,
        "summary": await repo.latency_summary(win, identity.user_id),
        "series": await repo.latency_series(win, identity.user_id),
    }


@router.get("/throughput")
async def throughput(
    win=Depends(_window),
    repo: MetricsRepository = Depends(get_repository),
    identity: Identity = Depends(get_identity),
):
    return {"window": win.key, "series": await repo.throughput_series(win, identity.user_id)}


@router.get("/errors")
async def errors(
    win=Depends(_window),
    repo: MetricsRepository = Depends(get_repository),
    identity: Identity = Depends(get_identity),
):
    return {
        "window": win.key,
        "series": await repo.errors_series(win, identity.user_id),
        "recent": await repo.recent_errors(win, identity.user_id),
    }


@router.get("/tokens")
async def tokens(
    win=Depends(_window),
    repo: MetricsRepository = Depends(get_repository),
    identity: Identity = Depends(get_identity),
):
    return {"window": win.key, **await repo.tokens(win, identity.user_id)}


@router.get("/dashboard")
async def dashboard(
    win=Depends(_window),
    repo: MetricsRepository = Depends(get_repository),
    identity: Identity = Depends(get_identity),
):
    """One-shot payload powering the main dashboard page."""

    user_id = identity.user_id
    return {
        "window": win.key,
        "available_windows": available_windows(),
        "summary": await repo.summary(win, user_id),
        "latency": {
            "summary": await repo.latency_summary(win, user_id),
            "series": await repo.latency_series(win, user_id),
        },
        "throughput": await repo.throughput_series(win, user_id),
        "errors": await repo.errors_series(win, user_id),
        "providers": await repo.providers(win, user_id),
        "models": await repo.models(win, user_id),
        "tokens": await repo.tokens(win, user_id),
    }
