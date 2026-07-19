"""Metrics service FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from llm_obs_shared.db.session import Database
from llm_obs_shared.fastapi_obs import install_observability
from llm_obs_shared.logging import configure_logging, get_logger

from app.api import routes_metrics
from app.config import get_settings

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.service_name, settings.log_level)
    database = Database(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    app.state.database = database
    logger.info("metrics-service started")
    try:
        yield
    finally:
        await database.dispose()
        logger.info("metrics-service stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="LLM Observability — Metrics Service",
        version="0.1.0",
        description="Aggregated dashboard APIs over persisted inference telemetry.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def _db_ready() -> bool:
        return await app.state.database.healthcheck()

    install_observability(app, service_name=settings.service_name, readiness_checks={"database": _db_ready})
    app.include_router(routes_metrics.router)
    return app


app = create_app()
