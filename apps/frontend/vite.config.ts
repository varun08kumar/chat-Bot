import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Dev proxy mirrors the production ingress routing:
//   /api/metrics/*  -> metrics-service  (prefix stripped to /metrics/*)
//   /api/*          -> chat-service      (prefix stripped)
// The more specific /api/metrics rule is declared first so it wins.
const CHAT_TARGET = process.env.VITE_CHAT_TARGET ?? "http://localhost:8001";
const METRICS_TARGET = process.env.VITE_METRICS_TARGET ?? "http://localhost:8004";

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
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
      "/api": {
        target: CHAT_TARGET,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
