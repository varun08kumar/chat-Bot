# Failure & scaling test scripts

Standalone, runnable scripts that exercise real failure modes and scaling
behavior against the running stack — not a pytest suite, no test framework.
Each script is self-contained, idempotent (restores whatever
container/state it touched, whether it passes or fails), and prints
`PASS`/`FAIL` lines plus a summary.

Every script here was actually run against the live stack while building it
— several caught real bugs in the process (see "Findings" below), not just
hypothetical ones.

## Requirements

- The Docker Compose stack up (`python3 scripts/dev_up.py` from the repo root)
- `docker`, `curl`, `python3` (stdlib only) for scripts `01`-`50`
- `kind`, `kubectl`, `k6` additionally for `60_scaling_hpa.sh`

## Running

```bash
cd scripts/tests

./01_health_liveness_all.sh          # run one script
./run_all.sh                          # run everything, in order
./run_all.sh --skip-slow               # everything except the HPA test (60)
./run_all.sh 10 11 16                  # only these scripts (by numeric prefix)
```

## What's covered

| # | Script | Checks |
|---|---|---|
| 01 | `health_liveness_all` | `GET /health` on all 4 backend services + frontend |
| 02 | `health_readiness_all` | `GET /health/ready` reports the *actual* declared dependency per service (chat: db+redis, ingestion: worker, consumer: db+worker, metrics: db) |
| 10 | `chat_postgres_down` | chat-service readiness flips to 503; `/chat` fails cleanly (5xx); recovers once Postgres returns |
| 11 | `chat_redis_down` | non-streaming `/chat` fails **open** (rate limiter/cache degrade, still 200); streaming path's real behavior when its job-queue dependency is down |
| 12 | `chat_kafka_down` | `/chat` still completes normally — the SDK's fire-and-forget design is proven, not assumed |
| 13 | `chat_llm_provider_error` | an invalid model → clean `502`, not a crash; service unaffected for the next request |
| 14 | `chat_searxng_down` | a question likely to trigger `web_search` still completes when SearXNG is down |
| 15 | `chat_worker_crash_recovery` | kills the chat-service container mid-stream (real `docker kill`, not simulated) and verifies the Redis-partial-buffer recovery persists an **honest continuation**, not a silently regenerated answer, with no duplicate message |
| 16 | `chat_explicit_cancel` | `POST /chat/{request_id}/cancel` stops generation near-immediately, mirroring the frontend's actual call order (cancel first, then disconnect) |
| 17 | `chat_multiuser_isolation` | 3 concurrent accounts never see each other's conversations; cross-account fetch by id → 404 |
| 18 | `chat_rate_limit_enforcement` | the 60-req/60s limiter actually returns 429 once exceeded (complements 11's fail-open check) |
| 20 | `ingestion_kafka_down` | survives without crash-looping; documents that its readiness check only reflects a `running` flag, not live Kafka connectivity |
| 21 | `ingestion_pii_redaction` | a real message with an email/card/phone is redacted (`[REDACTED_*]`) in the persisted `inference_logs.prompt_preview` — checked directly in Postgres |
| 22 | `ingestion_malformed_message_dlq` | a genuinely malformed message (published directly to Kafka, bypassing the SDK) is dead-lettered, not lost; the partition isn't stalled for messages after it |
| 30 | `consumer_postgres_down` | readiness flips to 503; recovers once Postgres returns |
| 31 | `consumer_kafka_down` | survives without crash-looping |
| 32 | `consumer_idempotent_replay` | the same event published twice results in exactly one row (`ON CONFLICT DO NOTHING` on `request_id`) |
| 40 | `metrics_postgres_down` | readiness flips to 503; dashboard query fails cleanly; recovers |
| 50 | `frontend_backend_down` | the static SPA shell still serves when chat-service is down; the `/api` proxy path fails cleanly, not a hang |
| 60 | `scaling_hpa` | **slow** (several minutes) — stands up a real `kind` cluster, deploys chat-service + its HPA, drives 800 VUs through `/chat/dummy`, and asserts real scale-up *and* scale-down, not just that the manifest exists |
| 61 | `scaling_partition_bound_consumers` | verifies the actual running Kafka topics' partition count against the ingestion/consumer HPAs' `maxReplicas` cap, and that each consumer group is actively consuming |

## Findings surfaced while building this suite

These aren't test bugs — they're real issues the tests caught, left as-is (or fixed separately) rather than papered over:

- **`consumer-service` was silently failing every write for ~2 days** (fixed during this build): it had been running continuously since before the Postgres password was last rotated, so its baked-in `DATABASE_URL` env var went stale. Every batch was retried, exhausted, and dead-lettered. Recreating the container (not just `restart`, which doesn't re-read `.env`) fixed it — script `02` now checks this going forward.
- **Streaming `/chat` hangs, rather than failing cleanly, when Redis is down** (script `11`): `stream_via_queue()`'s `pubsub.subscribe()`/`job_queue.enqueue()` calls have no explicit connect/operation timeout, so an unreachable Redis blocks on the OS-level TCP timeout instead of raising quickly. Not fixed yet — flagged as a known gap.
- **`ingestion-service`'s readiness check can't detect a live Kafka outage** (script `20`): `_worker_ready()` only reflects a `running` flag set once at startup, not real connectivity — `/health/ready` stays `200` throughout a Kafka outage.
- **Local Kafka topics have drifted to 1 partition instead of the documented 3** (script `61`): `kafka-init`'s `--create --if-not-exists` is a no-op on a topic that already exists from an older setup, so this long-lived local environment silently diverged from what `infra/k8s`'s `maxReplicas: 3` caps assume. Fixing it means deleting and recreating the topic (destructive to any unconsumed messages), so it's left as a flagged finding rather than auto-fixed.
