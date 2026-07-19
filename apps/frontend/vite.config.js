var _a, _b;
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
// Dev proxy mirrors the production ingress routing:
//   /api/metrics/*  -> metrics-service  (prefix stripped to /metrics/*)
//   /api/*          -> chat-service      (prefix stripped)
// The more specific /api/metrics rule is declared first so it wins.
var CHAT_TARGET = (_a = process.env.VITE_CHAT_TARGET) !== null && _a !== void 0 ? _a : "http://localhost:8001";
var METRICS_TARGET = (_b = process.env.VITE_METRICS_TARGET) !== null && _b !== void 0 ? _b : "http://localhost:8004";
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: { "@": path.resolve(__dirname, "src") },
    },
    server: {
        port: 5173,
        proxy: {
            "/api/metrics": {
                target: METRICS_TARGET,
                changeOrigin: true,
                rewrite: function (p) { return p.replace(/^\/api/, ""); },
            },
            "/api": {
                target: CHAT_TARGET,
                changeOrigin: true,
                rewrite: function (p) { return p.replace(/^\/api/, ""); },
            },
        },
    },
    build: {
        outDir: "dist",
        sourcemap: false,
    },
});
