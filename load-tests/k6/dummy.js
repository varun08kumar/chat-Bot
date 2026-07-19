// k6 concurrency-ceiling probe against the /chat/dummy endpoint.
//
// Unlike chat.js / dashboard.js, this isn't a fixed profile — VUS and
// DURATION are passed directly so run.sh (or the caller) can step the
// concurrency up between runs while watching host memory.
//
// Env:
//   BASE_URL   default http://localhost:8001
//   VUS        target concurrent virtual users (default 500)
//   DURATION   hold duration at target VUs (default 20s)
//
// Run:  k6 run -e VUS=5000 -e DURATION=20s load-tests/k6/dummy.js

import http from "k6/http";
import { check } from "k6";
import { Trend, Rate } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8001";
const VUS = parseInt(__ENV.VUS || "500", 10);
const DURATION = __ENV.DURATION || "20s";

const dummyLatency = new Trend("dummy_latency_ms", true);
const dummyErrors = new Rate("dummy_errors");

export const options = {
  scenarios: {
    dummy: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "10s", target: VUS },
        { duration: DURATION, target: VUS },
        { duration: "5s", target: 0 },
      ],
      gracefulRampDown: "5s",
      gracefulStop: "10s",
    },
  },
  thresholds: {
    dummy_errors: [{ threshold: "rate<1.0", abortOnFail: false }],
  },
  // Don't let k6 itself buffer unbounded response/discard data across huge VU counts.
  discardResponseBodies: false,
};

export default function () {
  const body = JSON.stringify({ message: "ping", model: "dummy", stream: false });
  const params = {
    headers: { "Content-Type": "application/json" },
    timeout: "10s",
  };
  const start = Date.now();
  const res = http.post(`${BASE_URL}/chat/dummy`, body, params);
  dummyLatency.add(Date.now() - start);
  const ok = check(res, { "status is 200": (r) => r.status === 200 });
  dummyErrors.add(!ok);
}
