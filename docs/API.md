# API Reference

Interactive OpenAPI docs are served per service at `/docs` (Swagger) and
`/redoc`. This page summarizes the public surface.

Identity is passed via headers (an auth gateway would set these in production):

- `X-User-Id` — owner of conversations (defaults to `demo-user`)
- `X-Session-Id` — session grouping (auto-generated if absent)
- `X-Correlation-ID` — optional; echoed back and propagated through the pipeline

---

## Chat Service — `http://localhost:8001`

### `POST /chat`
Send a message. Streams SSE by default; returns JSON when `stream: false`.

Request:
```json
{ "message": "Hello!", "conversation_id": null, "model": "gpt-4o-mini", "stream": true }
```

**SSE events** (`text/event-stream`):

| event   | data                                                        |
|---------|-------------------------------------------------------------|
| `start` | `{ conversation_id, request_id, model, provider }`          |
| `token` | `{ content }` — incremental text                            |
| `usage` | `{ prompt_tokens, completion_tokens, total_tokens }`       |
| `done`  | `{ conversation_id, usage }`                                |
| `error` | `{ message }`                                               |

**JSON** (`stream: false`):
```json
{
  "conversation_id": "…", "request_id": "…", "message": "Hi there!",
  "model": "gpt-4o-mini", "provider": "openai",
  "usage": { "prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13 },
  "latency_ms": 742.1
}
```

Cancel a stream by aborting the HTTP request (the UI "Stop" button); partial
output is persisted and the call is logged as `cancelled`. Rate limiting returns
`429` with `Retry-After`.

### `GET /conversations?search=&limit=&offset=`
List the caller's conversations (most-recently-updated first).

### `GET /conversation/{id}`
Full conversation with messages.

### `DELETE /conversation/{id}`
Soft-delete. Returns `{ "deleted": true }`.

### `GET /providers`
Providers and models, each flagged `enabled` when its API key is configured.

---

## Metrics Service — `http://localhost:8004`

All endpoints accept `?window=15m|1h|6h|24h|7d|30d` (default `24h`).

| Endpoint               | Returns                                                   |
|------------------------|-----------------------------------------------------------|
| `GET /metrics/providers`  | Per-provider requests, errors, avg latency, tokens     |
| `GET /metrics/models`     | Per-model usage and error rate                         |
| `GET /metrics/latency`    | avg / p50 / p95 / p99 summary + time series            |
| `GET /metrics/throughput` | Requests + RPS time series                             |
| `GET /metrics/errors`     | Error-rate time series + recent errors                 |
| `GET /metrics/tokens`     | Token totals and per-provider breakdown                |
| `GET /metrics/dashboard`  | Everything above in one payload (powers the UI)        |

---

## Common (every service)

| Endpoint          | Purpose                                             |
|-------------------|-----------------------------------------------------|
| `GET /health`     | Liveness — process is serving                        |
| `GET /health/ready` | Readiness — dependencies reachable (503 if not)    |
| `GET /metrics`    | Prometheus exposition                                |

> Note: on the metrics service, `GET /metrics` is the Prometheus endpoint while
> `GET /metrics/<name>` are the dashboard APIs — distinct paths, no collision.
