"""Dependency wiring for the metrics service."""

from __future__ import annotations

from fastapi import Depends, Request
from llm_obs_shared.db.session import Database

from app.repository import MetricsRepository


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_repository(db: Database = Depends(get_database)) -> MetricsRepository:
    return MetricsRepository(db)
