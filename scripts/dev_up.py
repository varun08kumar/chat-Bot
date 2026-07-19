#!/usr/bin/env python3
"""Bring up the local Docker Compose stack and wait until it's ready.

    python3 scripts/dev_up.py          # build + start, wait for health
    python3 scripts/dev_up.py --down   # tear the stack down
    python3 scripts/dev_up.py --logs   # follow logs after starting
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT / "infra" / "docker" / "docker-compose.yml"
ENV_FILE = ROOT / ".env"

# (name, URL) health checks polled after `compose up -d --build`.
HEALTH_CHECKS = [
    ("chat-service", "http://localhost:8001/health"),
    ("metrics-service", "http://localhost:8004/health"),
    ("frontend", "http://localhost:3000"),
]

URLS = {
    "Chat UI": "http://localhost:3000",
    "Dashboard": "http://localhost:3000/dashboard",
    "Chat API (OpenAPI)": "http://localhost:8001/docs",
    "Metrics API": "http://localhost:8004/docs",
    "Kafka UI": "http://localhost:8080",
    "Prometheus": "http://localhost:9090",
    "Grafana": "http://localhost:3001 (admin/admin)",
}


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    # Compose resolves ".env" relative to the compose file's directory
    # (infra/docker/), not the repo root, so it must be pointed at explicitly
    # or provider API keys silently come through empty inside the containers.
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), "--env-file", str(ENV_FILE), *args]
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=ROOT, check=check)


def wait_for_health(timeout_s: int = 180) -> bool:
    deadline = time.monotonic() + timeout_s
    pending = dict(HEALTH_CHECKS)
    while pending and time.monotonic() < deadline:
        for name, url in list(pending.items()):
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    if resp.status < 500:
                        print(f"  ✓ {name} is up ({url})")
                        del pending[name]
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass
        if pending:
            time.sleep(3)
    if pending:
        print(f"  ✗ still waiting on: {', '.join(pending)}", file=sys.stderr)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--down", action="store_true", help="stop and remove the stack")
    parser.add_argument("--logs", action="store_true", help="follow logs after starting")
    parser.add_argument("--no-wait", action="store_true", help="skip the readiness poll")
    args = parser.parse_args()

    if not COMPOSE_FILE.exists():
        print(f"compose file not found: {COMPOSE_FILE}", file=sys.stderr)
        return 1

    if args.down:
        compose("down")
        return 0

    compose("up", "-d", "--build")

    if not args.no_wait:
        print("\nWaiting for services to become healthy…")
        if not wait_for_health():
            print("\nSome services did not come up in time. Check `docker compose logs`.", file=sys.stderr)
            return 1

    print("\nStack is up:")
    for label, url in URLS.items():
        print(f"  {label:<20} {url}")

    if args.logs:
        compose("logs", "-f")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
