#!/usr/bin/env python3
"""Host-side Prometheus exporter for per-container CPU/memory.

cAdvisor can't reliably reach the Docker daemon from inside a container on
Docker Desktop for Mac (the daemon lives in Docker Desktop's own VM, not the
container's mount namespace). `docker stats` on the host CLI talks to the
same daemon fine, so this just polls it and serves the result as Prometheus
text format.

Run on the host (not in a container):

    python3 infra/docker/docker_stats_exporter.py [--port 9101] [--interval 5]

Prometheus (running in a container) reaches it via host.docker.internal,
which Docker Desktop resolves to the host automatically.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_latest_metrics = "# no data yet\n"
_lock = threading.Lock()


def _parse_bytes(s: str) -> float:
    """Parse a docker-stats size like '247.5MiB' into bytes."""
    m = re.match(r"([\d.]+)\s*([A-Za-z]+)", s.strip())
    if not m:
        return 0.0
    value, unit = float(m.group(1)), m.group(2)
    scale = {
        "B": 1, "kB": 1000, "MB": 1000**2, "GB": 1000**3,
        "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3,
    }
    return value * scale.get(unit, 1)


def _poll_loop(interval: float) -> None:
    global _latest_metrics
    while True:
        try:
            out = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
                capture_output=True, text=True, timeout=10, check=True,
            ).stdout
            lines = []
            lines.append("# HELP container_cpu_percent CPU usage percent reported by `docker stats`.")
            lines.append("# TYPE container_cpu_percent gauge")
            lines.append("# HELP container_memory_usage_bytes Memory usage in bytes reported by `docker stats`.")
            lines.append("# TYPE container_memory_usage_bytes gauge")
            lines.append("# HELP container_memory_limit_bytes Memory limit in bytes reported by `docker stats`.")
            lines.append("# TYPE container_memory_limit_bytes gauge")
            for line in out.strip().splitlines():
                row = json.loads(line)
                name = row["Name"]
                cpu = float(row["CPUPerc"].rstrip("%") or 0)
                mem_used_s, mem_limit_s = (row["MemUsage"].split(" / ") + ["0B"])[:2]
                mem_used = _parse_bytes(mem_used_s)
                mem_limit = _parse_bytes(mem_limit_s)
                lines.append(f'container_cpu_percent{{name="{name}"}} {cpu}')
                lines.append(f'container_memory_usage_bytes{{name="{name}"}} {mem_used}')
                lines.append(f'container_memory_limit_bytes{{name="{name}"}} {mem_limit}')
            with _lock:
                _latest_metrics = "\n".join(lines) + "\n"
        except Exception as exc:  # noqa: BLE001 - exporter must never crash the poll loop
            with _lock:
                _latest_metrics = f"# error polling docker stats: {exc}\n"
        time.sleep(interval)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        with _lock:
            body = _latest_metrics.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # noqa: A002 - silence per-request logging
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=9101)
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()

    threading.Thread(target=_poll_loop, args=(args.interval,), daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"docker_stats_exporter listening on :{args.port}/metrics (poll every {args.interval}s)")
    server.serve_forever()


if __name__ == "__main__":
    main()
