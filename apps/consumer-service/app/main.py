"""Consumer service: Kafka→PostgreSQL worker with an HTTP health/metrics surface."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from llm_obs_shared.db.session import Database
from llm_obs_shared.fastapi_obs import install_observability
from llm_obs_shared.logging import configure_logging, get_logger

from app.config import get_settings
from app.consumer import PersistenceConsumer
from app.repository import InferenceLogRepository

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
    repository = InferenceLogRepository(database)
    consumer = PersistenceConsumer(settings, repository)
    await consumer.start()

    app.state.database = database
    app.state.consumer = consumer
    worker = asyncio.create_task(consumer.run(), name="consumer-worker")
    logger.info("consumer-service started")
    try:
        yield
    finally:
        consumer.request_stop()
        try:
            await asyncio.wait_for(worker, timeout=20)
        except asyncio.TimeoutError:
            worker.cancel()
        await consumer.stop()
        await database.dispose()
        logger.info("consumer-service stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="LLM Observability — Consumer Service", version="0.1.0", lifespan=lifespan)

    async def _db_ready() -> bool:
        return await app.state.database.healthcheck()

    async def _worker_ready() -> bool:
        consumer = getattr(app.state, "consumer", None)
        return bool(consumer and consumer.running)

    install_observability(
        app,
        service_name=settings.service_name,
        readiness_checks={"database": _db_ready, "consumer": _worker_ready},
    )
    return app


app = create_app()
