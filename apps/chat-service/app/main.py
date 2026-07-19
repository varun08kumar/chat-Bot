"""Chat service FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from llm_obs_sdk import SdkConfig, configure_sdk, shutdown_sdk
from llm_obs_shared.fastapi_obs import install_observability
from llm_obs_shared.logging import configure_logging, get_logger
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import routes_chat, routes_conversations
from app.config import get_settings
from app.dependencies import AppContainer

logger = get_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Minimal 'helmet-equivalent' response hardening."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-XSS-Protection", "0")
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.service_name, settings.log_level)

    # Start the observability SDK (async Kafka producer).
    await configure_sdk(
        SdkConfig(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            client_id=f"{settings.service_name}-sdk",
            topic=settings.inference_topic,
            security_protocol=settings.kafka_security_protocol,
        )
    )

    container = AppContainer.build(settings)
    app.state.container = container
    logger.info("chat-service started", extra={"environment": settings.environment})
    try:
        yield
    finally:
        await container.aclose()
        await shutdown_sdk()
        logger.info("chat-service stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="LLM Observability — Chat Service",
        version="0.1.0",
        description="Multi-provider chat API with SSE streaming and automatic inference logging.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )
    app.add_middleware(SecurityHeadersMiddleware)

    async def _db_ready() -> bool:
        return await app.state.container.database.healthcheck()

    async def _redis_ready() -> bool:
        try:
            return bool(await app.state.container.redis.ping())
        except Exception:  # noqa: BLE001
            return False

    install_observability(
        app,
        service_name=settings.service_name,
        readiness_checks={"database": _db_ready, "redis": _redis_ready},
    )

    app.include_router(routes_chat.router)
    app.include_router(routes_conversations.router)
    return app


app = create_app()
