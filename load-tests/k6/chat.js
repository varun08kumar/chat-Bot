// k6 load test for the chat pipeline.
//
// Profiles (set PROFILE=smoke|100|1000|5000|10000):
//   smoke  – 5 VUs, quick sanity check
//   100    – 100 concurrent users
//   1000   – 1k concurrent users
//   5000   – 5k concurrent users
//   10000  – 10k concurrent users
//
// Env:
//   BASE_URL   default http://localhost:8001
//   STREAM     "true" to exercise the SSE path, else non-streaming JSON
//   MODEL      model id (default gpt-4o-mini)
//
// Run:  k6 run -e PROFILE=100 -e BASE_URL=http://localhost:8001 load-tests/k6/chat.js

import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Rate, Counter } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8001";
const MODEL = __ENV.MODEL || "gpt-4o-mini";
const STREAM = (__ENV.STREAM || "false") === "true";
const PROFILE = __ENV.PROFILE || "smoke";

const chatLatency = new Trend("chat_latency_ms", true);
const chatErrors = new Rate("chat_errors");
const chatRequests = new Counter("chat_requests");

const PROFILES = {
  smoke: { vus: 5, duration: "30s" },
  "100": { vus: 100, duration: "2m" },
  "1000": { vus: 1000, duration: "3m" },
  "5000": { vus: 5000, duration: "3m" },
  "10000": { vus: 10000, duration: "3m" },
};

const selected = PROFILES[PROFILE] || PROFILES.smoke;

export const options = {
  scenarios: {
    chat: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "30s", target: selected.vus },
        { duration: selected.duration, target: selected.vus },
        { duration: "20s", target: 0 },
      ],
      gracefulRampDown: "20s",
    },
  },
  thresholds: {
    // p95 < 3s, p99 < 8s for the (LLM-bound) chat call.
    chat_latency_ms: ["p(95)<3000", "p(99)<8000"],
    chat_errors: ["rate<0.05"],
    http_req_duration: ["p(95)<5000"],
  },
};

const PROMPTS = [
  "Explain event-driven architecture in one sentence.",
  "What is Kafka consumer lag?",
  "Give me a haiku about observability.",
  "Summarize the CAP theorem briefly.",
  "Why use exponential backoff?",
];

export default function () {
  const body = JSON.stringify({
    message: PROMPTS[Math.floor(Math.random() * PROMPTS.length)],
    model: MODEL,
    stream: STREAM,
  });
  const params = {
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": `loadtest-${__VU}`,
      "X-Session-Id": `session-${__VU}`,
      Accept: STREAM ? "text/event-stream" : "application/json",
    },
    timeout: "60s",
  };

  const start = Date.now();
  const res = http.post(`${BASE_URL}/chat`, body, params);
  chatLatency.add(Date.now() - start);
  chatRequests.add(1);

  const ok = check(res, {
    "status is 200": (r) => r.status === 200,
    "has body": (r) => r.body && r.body.length > 0,
  });
  chatErrors.add(!ok);

  sleep(Math.random() * 2 + 1); // 1-3s think time
}
