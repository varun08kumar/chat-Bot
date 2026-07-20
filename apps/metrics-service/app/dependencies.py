"""Dependency wiring for the metrics service."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Cookie, Depends, HTTPException, Request, status
from llm_obs_shared.db.session import Database

from app.config import Settings, get_settings
from app.repository import MetricsRepository
from app.services.auth import TokenError, verify_token


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_repository(db: Database = Depends(get_database)) -> MetricsRepository:
    return MetricsRepository(db)


@dataclass(frozen=True)
class Identity:
    user_id: str


def get_identity(
    access_token: str | None = Cookie(default=None, alias="access_token"),
    settings: Settings = Depends(get_settings),
) -> Identity:
    """Resolve the caller from the same access-token cookie chat-service
    issues — the dashboard is a personal usage view, scoped to whoever is
    logged in, not an admin panel (see the Grafana "Per-User Usage"
    dashboard for the all-users view)."""

    if access_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = verify_token(access_token, expected_type="access", settings=settings)
    except TokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return Identity(user_id=payload.user_id)
