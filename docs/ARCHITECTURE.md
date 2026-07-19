# Architecture

## Overview

The platform separates the **user-facing hot path** (chat) from the
**telemetry pipeline** (logging → processing → storage → dashboards) so that
observability can never degrade the user experience. Communication between
stages is asynchronous over Kafka.

```
Frontend ──HTTP/SSE──► Chat Service ──► LiteLLM ──► LLM provider
                            │
                        @observe_llm (SDK)
                            │  (fire-and-forget, in-memory queue)
                            ▼
                   Kafka topic: inference.logs
                            │
                   Ingestion Service  (validate · PII redact · normalize)
                            ▼
                   Kafka topic: processed.logs
                            │
                   Consumer Service   (batch · retry/backoff · DLQ · idempotent)
                            ▼
                       PostgreSQL
                          ▲   ▲
             Metrics Svc ─┘   └─ (Grafana panels via Prometheus scrape of all svcs)
```

## Design principles

- **Logging never blocks inference.** The SDK enqueues events into a bounded
  in-memory queue and returns immediately. A background task drains the queue to
  Kafka with retries. On overflow the *oldest* event is dropped — bounded memory,
  never back-pressure on the request.
- **Event-driven & decoupled.** Services share only the Kafka event contracts
  (`InferenceLogEvent`, `ProcessedLogEvent`) defined once in `packages/shared`.
- **At-least-once + idempotent.** Consumers commit offsets only after durable
  handling; inserts use `ON CONFLICT DO NOTHING` keyed on `request_id`, so replays
  after a crash never duplicate rows.
- **Clean architecture.** Each service is layered: API → service → repository,
  with dependency injection at the edges and no SQL outside repositories.

## Components

### Chat Service (`apps/chat-service`)
FastAPI. Owns conversations and messages. Streams tokens via SSE (`sse-starlette`)
and supports non-streaming JSON. Uses Redis for a recent-messages cache, session
cache and a fixed-window rate limiter (all fail-open). Multi-provider via LiteLLM;
adding a provider is a registry entry in `services/providers.py`. Cancellation is
handled by detecting client disconnect and aborting the stream, still persisting
partial output and logging the call as `cancelled`.

### SDK (`packages/sdk`)
`@observe_llm` wraps sync/async inference functions, extracting metadata
defensively from LiteLLM/OpenAI-shaped responses. `observe_stream` covers the SSE
path. A singleton `KafkaLogProducer` owns the async producer and drain worker.

### Ingestion Service (`apps/ingestion-service`)
Consumes `inference.logs`. Validates against the Pydantic schema, applies PII
redaction (emails, cards, SSNs, API keys, IPs, phones) to previews and string
metadata, normalizes provider/model, and republishes to `processed.logs`.
Un-parseable messages go to `dead-letter`.

### Consumer Service (`apps/consumer-service`)
Consumes `processed.logs` in batches, writes to PostgreSQL in a single
transaction with the `provider_stats` rollup, retries transient DB failures with
exponential backoff, and dead-letters a batch that exhausts its retries.

### Metrics Service (`apps/metrics-service`)
Read-only. Parameterized SQL aggregations over `inference_logs` (percentiles via
`percentile_cont`, throughput via epoch bucketing) power the dashboard APIs.

## Data model

`conversations`, `messages`, `inference_logs`, `provider_stats` — see
`packages/shared/llm_obs_shared/db/models.py`. Indexes cover the dashboard access
patterns: `inference_logs(timestamp)`, `(provider, timestamp)`, `(model,
timestamp)`, `(status, timestamp)`, `(conversation_id)`; `messages(conversation_id,
created_at)`; `conversations(user_id, updated_at)`.

## Correlation & tracing

Each inbound request is assigned (or inherits) a correlation id via the
`X-Correlation-ID` header, bound to a `ContextVar` and attached to every log line
and Kafka event. The design leaves clean seams for OpenTelemetry span export.

## Scaling

- **Chat / Metrics** scale horizontally on CPU/memory (HPA), stateless.
- **Ingestion / Consumer** scale up to the topic partition count (3 by default);
  Kafka consumer groups balance partitions across replicas.
- **Kafka partitioning** keys on `conversation_id` so a conversation's events keep
  order.
```
