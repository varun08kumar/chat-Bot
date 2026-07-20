# LLM Observability Platform

A production-style, event-driven platform for logging and observing Large
Language Model inference. A multi-provider chatbot streams responses to users
while **every inference is automatically instrumented** and shipped through
Kafka to PostgreSQL - without ever blocking the user request.

```
                          Internet
                             │
                       NGINX Ingress
                             │
                     React Frontend (Vite)
                             │
              REST + SSE ┌───┴────────────┐ REST
                         ▼                 ▼
                   Chat Service      Metrics Service ──► PostgreSQL (reads)
                         │
                     LiteLLM (OpenAI / Anthropic / Groq / Gemini …)
                         │
                @observe_llm SDK  ──► Kafka: inference.logs
                                            │
                                    Ingestion Service
                                    (validate · redact PII · normalize)
                                            │
                                     Kafka: processed.logs
                                            │
                                    Consumer Service
                                    (batch insert · retry/backoff · DLQ)
                                            │
                                        PostgreSQL ◄── Grafana ◄── Prometheus
                                                        (scrapes every service)
```

See **[docs/SYSTEM_DOCUMENTATION.html](docs/SYSTEM_DOCUMENTATION.html)** for a
full screen-by-screen tour with live screenshots plus architecture/sequence
diagrams (open it directly in a browser - self-contained, no server needed),
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the telemetry-pipeline
deep dive, **[docs/API.md](docs/API.md)** for endpoint reference,
**[docs/WALKTHROUGH.md](docs/WALKTHROUGH.md)** for an earlier screen tour, and
**[docs/LOAD_TESTING.md](docs/LOAD_TESTING.md)** for load-testing methodology,
results, and the Kubernetes autoscaling demo.

---

## Quickstart

```bash
git clone <repo> && cd llm-observability
cp .env.example .env
```

Then edit `.env` and fill in two things - **both required**, the stack won't
start without them:

1. **At least one LLM provider key** - `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
   `GROQ_API_KEY`, or `GEMINI_API_KEY`. If you set `DEFAULT_MODEL` to a model
   from a different provider than your key, override it to match.
2. **`JWT_SECRET`** - signs the login session tokens. Generate a real one:
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
   Paste the output as `JWT_SECRET=...`. Don't leave it blank or reuse this
   README's example - `chat-service` and `metrics-service` both refuse to
   boot without it (`docker compose` fails fast with a clear error instead of
   starting half-configured).

3. **Change `POSTGRES_PASSWORD` and `GRAFANA_PASSWORD`** away from the
   `.env.example` defaults (`postgres` / `admin`) before this stack is
   reachable by anyone but you - `.env.example` itself is committed and
   pushed, so those defaults are effectively public. Anything else you'd
   normally treat as a real credential (a shared/hosted deployment, a demo
   someone else can reach) needs its own unique value here too.

   > **If the stack is already running** with the old defaults, changing
   > `.env` alone does nothing - Postgres and Grafana both only apply
   > `POSTGRES_PASSWORD`/`GF_SECURITY_ADMIN_PASSWORD` on their *first* boot
   > against a fresh data volume; an existing volume keeps the old password
   > regardless of what the env var says on restart. Update the running
   > instances directly instead:
   > ```bash
   > docker exec llm-observability-postgres-1 psql -U postgres -c \
   >   "ALTER USER postgres WITH PASSWORD '<new password>';"
   > docker exec llm-observability-grafana-1 grafana-cli admin reset-admin-password '<new password>'
   > ```
   > Then update `POSTGRES_PASSWORD`/`DATABASE_URL`/`GRAFANA_PASSWORD` in
   > `.env` to match, and restart the services that hold a `DATABASE_URL`
   > connection (`chat-service`, `metrics-service`) so they pick it up.

Then bring the stack up:

```bash
docker compose -f infra/docker/docker-compose.yml up --build
# or, equivalently, with health-check polling and a summary of URLs:
python3 scripts/dev_up.py
```

One command brings up the frontend, all four services, Kafka (+ UI),
PostgreSQL, Redis, Prometheus and Grafana. Database migrations run
automatically via the `migrate` job, and Kafka topics are created by
`kafka-init`.

Open **http://localhost:3000**, click **Sign up** to create an account (self-
service, no invite needed), and start chatting.

| Surface              | URL                                  |
|-----------------------|--------------------------------------|
| Chat UI               | http://localhost:3000                |
| Log in / Sign up      | http://localhost:3000/login · /register |
| Dashboard (your usage)| http://localhost:3000/dashboard      |
| Chat API (OpenAPI)    | http://localhost:8001/docs           |
| Metrics API           | http://localhost:8004/docs           |
| Kafka UI              | http://localhost:8080                |
| Prometheus            | http://localhost:9090                |
| Grafana (all-users)   | http://localhost:3001 (admin/admin)  |

> Without a provider key the UI still loads; chat calls will return a
> provider error which is itself logged through the pipeline (failures are
> first-class telemetry). Without `JWT_SECRET` set, the stack won't start at
> all - see above.

---

## Services

| Service              | Port | Role                                                             |
|----------------------|------|-----------------------------------------------------------------|
| `frontend`           | 3000 | React/Vite SPA - chat + live dashboard                          |
| `chat-service`       | 8001 | Chat API, SSE streaming, conversations, SDK auto-logging        |
| `ingestion-service`  | 8002 | Consumes `inference.logs` → validate/redact/normalize → publish |
| `consumer-service`   | 8003 | Consumes `processed.logs` → batched idempotent inserts          |
| `metrics-service`    | 8004 | Read-only dashboard aggregation APIs                            |

Shared code lives in `packages/`:

- **`packages/shared`** - event schemas, structured logging, correlation IDs,
  Prometheus metrics, ASGI middleware, SQLAlchemy models + Alembic migrations,
  reusable Kafka helpers.
- **`packages/sdk`** - the `@observe_llm` decorator and non-blocking async Kafka
  producer.

Every service exposes `GET /health`, `GET /health/ready` and `GET /metrics`.

---

## The `@observe_llm` SDK

Instrumenting inference is a single decorator:

```python
from llm_obs_sdk import observe_llm

@observe_llm(endpoint="/chat")
async def complete(*, model, messages):
    return await litellm.acompletion(model=model, messages=messages)
```

It automatically captures provider, model, latency, prompt/completion/total
tokens, status, errors, request/session/conversation ids, endpoint, provider
metadata, and **200-char previews only** (full prompts are never logged). Events
are enqueued in-memory and drained by a background task - if Kafka is slow or
down, logging degrades (drops oldest, bounded memory) but inference is never
blocked or failed. Streaming responses use the `observe_stream` helper, which
emits the same event once the stream completes.

---

## Local development (without Docker)

Each service is an installable package. Example for the chat service:

```bash
python -m venv .venv && source .venv/bin/activate
pip install ./packages/shared[db,kafka] ./packages/sdk ./apps/chat-service
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/llm_observability
alembic -c packages/shared/alembic.ini upgrade head
uvicorn app.main:app --port 8001 --reload
```

Frontend:

```bash
cd apps/frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to the services
```

---

## Authentication

Self-signup accounts (register → immediately logged in, no invite/approval
step). Two JWTs, both set as `httpOnly` cookies so they're never readable by
JavaScript: a short-lived **access token** (3 min) sent on every request, and
a long-lived **refresh token** (7 days) the frontend silently exchanges for a
fresh pair every 2 minutes in the background. A third, non-`httpOnly` CSRF
cookie is echoed back as a header on mutating requests (double-submit
pattern) - `httpOnly` alone doesn't stop CSRF, since the browser attaches
cookies to *any* site's request to this origin.

Two dashboards exist because two different questions need answering:

| | Scope | Access |
|---|---|---|
| **In-app `/dashboard`** | Your own usage only - `metrics-service` filters every query by the caller's JWT `user_id` | Any logged-in account, their own data only |
| **Grafana "Per-User Usage"** | Every account's usage, filterable by user | Grafana's own separate admin login (`admin`/`admin`) - not reachable via any product account |

---

## Observability

- **Prometheus** scrapes `/metrics` on every service (HTTP, LLM, Kafka, DB and
  DLQ metrics - see `packages/shared/llm_obs_shared/metrics.py`) plus
  `kube-state-metrics` for cluster-level pod/deployment/node state.
- **Grafana** auto-provisions eight dashboards from `infra/grafana/dashboards/`:
  LLM Overview, Kafka Pipeline, Database, Application, Container Resources,
  Kubernetes Autoscaling (chat-service HPA), Cluster Overview (every
  deployment in the namespace), and Per-User Usage (raw SQL against Postgres,
  not Prometheus - a per-user metric label would be unbounded cardinality).
- **Structured JSON logs** with correlation IDs propagate across every hop via
  the `X-Correlation-ID` header.

---

## Reliability & failure handling

| Failure               | Behaviour                                                        |
|-----------------------|-----------------------------------------------------------------|
| Kafka slow/unavailable| SDK buffers in-memory (bounded, drop-oldest); inference unblocked|
| Invalid event         | Routed to the `dead-letter` topic; partition never stalls       |
| DB write fails        | Retried with exponential backoff; batch DLQ'd after the limit   |
| Consumer crash        | Resumes from the last committed offset; inserts are idempotent   |
| LLM timeout/error     | Graceful error to the user **and** still logged as a failure     |
| chat-service crash mid-response | The completion request is queued (Redis Streams), not called inline; any surviving replica reclaims and finishes the still-unacked job - verified by SIGKILL-ing a running container mid-stream and watching another replica pick it up |

---

## Schema design decisions

Full DDL: `packages/shared/llm_obs_shared/db/models.py` (four tables:
`conversations`, `messages`, `inference_logs`, `provider_stats`).

- **Chat data and telemetry are separate tables on separate write paths.**
  `conversations`/`messages` are written synchronously by chat-service inline
  with the request; `inference_logs` is written asynchronously, minutes or
  seconds later, by consumer-service off the Kafka pipeline. They're not even
  in the same transaction - a stalled telemetry pipeline can never block a
  chat response.
- **`inference_logs.request_id` is the idempotency key** (`UNIQUE`, inserted
  with `ON CONFLICT DO NOTHING`). Kafka's at-least-once delivery means the
  same event can arrive twice after a consumer crash/replay; this makes
  re-processing a no-op instead of a duplicate row.
- **Previews, not full text, in `inference_logs`.** `prompt_preview` /
  `response_preview` are truncated to 256 chars - full conversation content
  lives only in `messages`. This keeps the telemetry table's blast radius
  small if it's ever queried broadly or exported, and keeps rows cheap.
- **`metadata` is JSONB, not fixed columns.** Provider-specific fields
  (finish reason, cache hits, etc.) vary by provider and change over time;
  JSONB avoids a migration per new field. Tradeoff: no type safety, and it's
  currently unindexed - fine until a real query needs to filter on it (see
  "what I'd improve").
- **Composite indexes match actual dashboard queries, not added
  defensively**: `(provider, timestamp)`, `(model, timestamp)`,
  `(status, timestamp)` mirror exactly the `GROUP BY`/`WHERE` clauses
  metrics-service issues for percentiles and throughput bucketed by time.
- **IDs are opaque hex strings (`uuid4().hex`), not native `UUID` or
  auto-increment.** Keeps them URL-safe with no dashes for the frontend
  router (`/c/:id`) and avoids the ordering/enumeration information a serial
  PK leaks. The one exception is `inference_logs.id` (`BigInteger`
  autoincrement) - nothing external ever references a log row by ID, so it's
  purely an internal ordering convenience.
- **`provider_stats` is a small denormalized rollup**, not always computed
  from `inference_logs`. Cheap to read for the dashboard's provider panel,
  at the cost of consumer-service having to remember to update it on every
  insert - it can drift from the raw table if that logic and the table ever
  disagree.

## Tradeoffs made

- **Kafka event pipeline instead of the SDK POSTing straight to an ingestion
  HTTP endpoint.** More moving parts to run locally (a full broker) and more
  failure modes to reason about, but buys real decoupling - ingestion or the
  consumer can restart, fall behind, or crash without dropping chat traffic
  or losing already-produced events. A direct HTTP-POST version would have
  been faster to build and is a legitimate choice at lower volume.
- **Batched, idempotent inserts in consumer-service**, not one `INSERT` per
  event - trades a small amount of visibility latency (rows aren't in
  Postgres the instant they're produced) for materially higher write
  throughput and fewer round trips at volume.
- **Regex-based PII redaction**, not a trained NER/PII-detection model. Zero
  added latency, no extra dependency - but only catches structured patterns
  (email/card/SSN/API-key/IP/phone), not e.g. a name in free text.
  Documented as defense-in-depth, not a compliance guarantee.
- **Redis-backed rate limiting and message cache fail open** - Redis down
  means "no rate limit enforced" / "cache miss, read from Postgres instead,"
  not "chat is down." Availability over strict enforcement.
- **Single uvicorn worker per service** in Docker Compose (no
  `--workers`/gunicorn). Load testing (`docs/LOAD_TESTING.md`) found this
  caps chat-service at ~2,000 req/s on one CPU core - a deliberate tradeoff,
  since the intended scaling axis is horizontal replicas + the Kubernetes
  HPA, not a fatter single process.
- **Opaque string IDs over native Postgres `UUID`** - slightly larger
  on-disk (36 hex chars as text vs. 16 bytes binary), traded for simplicity
  across the JSON API boundary and readability in logs.

## What I'd improve with more time

- Retention/archival policy for `conversations`/`messages` - they currently
  grow unbounded, and deletion is a soft `status` flag, not a purge.
- Replace regex PII redaction with a proper NER-based detector, and redact
  *before* the `inference.logs` topic rather than only at ingestion - right
  now an unredacted preview briefly exists on that topic.
- OpenTelemetry span export. The correlation-ID plumbing
  (`X-Correlation-ID`, propagated end-to-end) was deliberately built to
  leave a clean seam for this; today it only feeds structured logs, not
  distributed traces.
- A GIN index on `inference_logs.metadata` (or promote a couple of hot
  fields to real columns) once a real query pattern needs to filter on it.
- Multi-worker/multi-process chat-service so a single instance isn't capped
  at one CPU core at the application level - currently only worked around
  via Kubernetes replica count, not fixed at the source.
- Push this to an actual GitHub repository with CI (lint/typecheck/test on
  every PR) - currently local-only.
- A hosted demo deployment - currently only reachable via local Docker
  Compose / a local `kind` cluster.

---

## Kubernetes

```bash
kubectl apply -k infra/k8s
```

Provides Deployments, Services, HPAs, ConfigMap/Secret, NetworkPolicies,
PodDisruptionBudgets, resource requests/limits, liveness/readiness probes, a
migration Job and an NGINX Ingress. Build & push the images first (tags
`llm-obs/<service>:0.1.0`).

---

## Load testing

k6 scripts for 100 / 1000 / 5000 / 10000 concurrent users:

```bash
./load-tests/run.sh chat 100
./load-tests/run.sh dashboard 5000
```

See [load-tests/README.md](load-tests/README.md).

---

## Repository layout

```
apps/
  frontend/            React + Vite + TS + Tailwind SPA
  chat-service/        FastAPI chat API (SSE, LiteLLM, Redis)
  ingestion-service/   Kafka validate/redact/normalize worker
  consumer-service/    Kafka → PostgreSQL persistence worker
  metrics-service/     Dashboard aggregation APIs
packages/
  shared/              Schemas, logging, metrics, DB models, migrations
  sdk/                 @observe_llm + async Kafka producer
infra/
  docker/              docker-compose stack
  k8s/                 Kubernetes manifests (kustomize)
  prometheus/          scrape config
  grafana/             datasource + dashboard provisioning
load-tests/            k6 scripts
docs/                  architecture, API reference & SYSTEM_DOCUMENTATION.html
```
