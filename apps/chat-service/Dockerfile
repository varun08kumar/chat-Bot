# syntax=docker/dockerfile:1
# Multi-stage build. Build context is the repo root so local monorepo packages
# (packages/shared, packages/sdk) can be installed alongside the service.

FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /build
COPY packages/shared ./packages/shared
COPY packages/sdk ./packages/sdk
COPY apps/chat-service ./apps/chat-service
RUN pip install ./packages/shared[db] ./packages/sdk ./apps/chat-service

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN useradd --create-home --uid 1000 appuser
COPY --from=builder /opt/venv /opt/venv
# Ship the migrations so the schema can be applied from this image.
COPY packages/shared/alembic.ini /app/alembic.ini
COPY packages/shared/migrations /app/migrations
WORKDIR /app
USER appuser
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/health').status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--proxy-headers"]
