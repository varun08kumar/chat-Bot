# Load Tests (k6)

Load tests for the chat pipeline and the dashboard query APIs.

## Prerequisites

- [k6](https://k6.io/docs/get-started/installation/)
- The platform running (`docker compose … up`) and reachable.

## Scenarios

| Profile   | Concurrent VUs |
|-----------|----------------|
| `smoke`   | 5              |
| `100`     | 100            |
| `1000`    | 1000           |
| `5000`    | 5000           |
| `10000`   | 10000          |

Each scenario ramps up, holds, and ramps down, and records:

- **Latency** (`chat_latency_ms` / `http_req_duration`)
- **P95 / P99** (via k6 thresholds)
- **Error rate** (`chat_errors` / `dashboard_errors`)
- **Throughput** (k6 `iterations` / `http_reqs` per second)

## Running

```bash
# Chat path (drives real LLM inference — mind provider cost at high VUs)
./run.sh chat 100
STREAM=true ./run.sh chat 1000          # exercise the SSE streaming path

# Read-heavy dashboard path (no LLM cost — safe to push to 10k)
./run.sh dashboard 5000
```

Or invoke k6 directly:

```bash
k6 run -e PROFILE=1000 -e BASE_URL=http://localhost:8001 k6/chat.js
```

> ⚠️ The 5000/10000 chat profiles will generate a very large number of real LLM
> calls. Use the `dashboard` test (or a mock provider) for pure infrastructure
> load testing to avoid provider cost and rate limits.

JSON summaries are written to `load-tests/results/`.

## Thresholds

The run fails (non-zero exit) if:

- Chat p95 ≥ 3s or p99 ≥ 8s
- Error rate ≥ 5% (chat) / 1% (dashboard)
- Dashboard p95 ≥ 800ms
