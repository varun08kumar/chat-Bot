"""Ingestion service: a Kafka worker with an HTTP surface for health/metrics."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from llm_obs_shared.fastapi_obs import install_observability
from llm_obs_shared.logging import configure_logging, get_logger

from app.config import get_settings
from app.consumer import IngestionConsumer
from app.pii import PiiRedactor
from app.processor import EventProcessor

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.service_name, settings.log_level)

    processor = EventProcessor(PiiRedactor(enabled=settings.pii_redaction_enabled))
    consumer = IngestionConsumer(settings, processor)
    await consumer.start()
    app.state.consumer = consumer
    worker = asyncio.create_task(consumer.run(), name="ingestion-worker")
    app.state.worker = worker
    logger.info("ingestion-service started")
    try:
        yield
    finally:
        consumer.request_stop()
        try:
            await asyncio.wait_for(worker, timeout=15)
        except asyncio.TimeoutError:
            worker.cancel()
        await consumer.stop()
        logger.info("ingestion-service stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="LLM Observability — Ingestion Service", version="0.1.0", lifespan=lifespan)

    async def _worker_ready() -> bool:
        consumer = getattr(app.state, "consumer", None)
        return bool(consumer and consumer.running)

    install_observability(
        app, service_name=settings.service_name, readiness_checks={"consumer": _worker_ready}
    )
    return app


app = create_app()
