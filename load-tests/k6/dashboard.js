// Read-heavy load test for the metrics/dashboard APIs (no LLM cost).
// Useful for load-testing the query path at high concurrency safely.
//
// Run: k6 run -e PROFILE=1000 -e BASE_URL=http://localhost:8004 load-tests/k6/dashboard.js

import http from "k6/http";
import { check, sleep } from "k6";
import { Rate } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8004";
const PROFILE = __ENV.PROFILE || "smoke";
const errors = new Rate("dashboard_errors");

const PROFILES = {
  smoke: 5,
  "100": 100,
  "1000": 1000,
  "5000": 5000,
  "10000": 10000,
};
const vus = PROFILES[PROFILE] || 5;

export const options = {
  scenarios: {
    dashboard: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "20s", target: vus },
        { duration: "1m", target: vus },
        { duration: "10s", target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_duration: ["p(95)<800", "p(99)<2000"],
    dashboard_errors: ["rate<0.01"],
  },
};

const WINDOWS = ["15m", "1h", "24h", "7d"];
const ENDPOINTS = ["/metrics/dashboard", "/metrics/latency", "/metrics/throughput", "/metrics/providers"];

export default function () {
  const w = WINDOWS[Math.floor(Math.random() * WINDOWS.length)];
  const e = ENDPOINTS[Math.floor(Math.random() * ENDPOINTS.length)];
  const res = http.get(`${BASE_URL}${e}?window=${w}`);
  errors.add(
    !check(res, {
      "status is 200": (r) => r.status === 200,
      "is json": (r) => (r.headers["Content-Type"] || "").includes("application/json"),
    }),
  );
  sleep(Math.random() + 0.5);
}
