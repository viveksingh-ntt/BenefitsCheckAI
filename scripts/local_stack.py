#!/usr/bin/env python3
"""Run the whole HealthGen stack locally (no Azure): six processes on localhost.

    python scripts/local_stack.py              # then open http://localhost:8080
    python scripts/local_stack.py --base 9100  # other ports (portal = base - 20)

    8101 healthgen-core-mock   8102 identity-broker   8103 mcp-healthgen
    8104 Direct Line emulator + agent relay           8105 foundry-local (scripted stand-in + hand-off stub)
    8080 portal-dev (host page + BFF)

The keys below are dev-only values for localhost.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]


def plan(base: int = 8100, db_dir: str | None = None) -> list[dict]:
    core, broker, mcp, relay, foundry = (base + i for i in range(1, 6))
    portal = 8080 if base == 8100 else base - 20
    db_dir = db_dir or tempfile.mkdtemp(prefix="healthgen-")

    def url(p: int) -> str:
        return f"http://localhost:{p}"

    common = {"LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"), "PYTHONUNBUFFERED": "1", "NO_PROXY": "localhost,127.0.0.1", "no_proxy": "localhost,127.0.0.1"}
    rows = [
        ("core", "services/healthgen-core-mock", "app.main:app", core,
         {"BROKER_ISSUER": url(broker), "CORE_JWKS_URL": f"{url(broker)}/.well-known/jwks.json"}),
        ("broker", "services/identity-broker", "app.main:app", broker,
         {"BROKER_ISSUER": url(broker), "DIRECTLINE_SECRET": "local-dev-secret", "DIRECTLINE_ENDPOINT": url(relay),
          "DIRECTLINE_TRUSTED_ORIGINS": url(portal), "PORTAL_ISSUERS": url(portal), "PORTAL_JWKS_URL": f"{url(portal)}/.well-known/jwks.json",
          "SERVICE_AUTH": "keys", "SERVICE_KEYS": "agent-relay=dev-relay-key,mcp-healthgen=dev-mcp-key,apim=dev-apim-key",
          "BROKER_DB_PATH": str(Path(db_dir) / "broker.db")}),
        ("mcp", "services/mcp-healthgen", "app.main:app", mcp,
         {"BROKER_URL": url(broker), "CORE_URL": url(core), "BROKER_CLIENT_KEY": "dev-mcp-key",
          "MCP_AUTH": "keys", "MCP_KEYS": "foundry=dev-foundry-mcp-key", "INTERNAL_AUTH": "keys", "INTERNAL_KEYS": "agent-relay=dev-relay-cards-key",
          "HANDOFF_WEBHOOK_URL": f"{url(foundry)}/webhook/healthgen-handoff", "HANDOFF_WEBHOOK_SECRET": "dev-handoff-secret"}),
        ("relay", "services/agent-relay", "dev_server:app", relay,
         {"BROKER_URL": url(broker), "BROKER_KEY": "dev-relay-key", "MCP_URL": url(mcp), "MCP_CARDS_KEY": "dev-relay-cards-key",
          "FOUNDRY_BASE_URL": f"{url(foundry)}/api/projects/healthgen", "FOUNDRY_KEY": "dev-foundry-key",
          "DIRECTLINE_SECRET": "local-dev-secret", "DEV_CORS_ORIGINS": url(portal)}),
        ("foundry", "services/foundry-local", "app:app", foundry,
         {"BROKER_ISSUER": url(broker), "BROKER_JWKS_URL": f"{url(broker)}/.well-known/jwks.json", "MCP_URL": url(mcp),
          "MCP_KEY": "dev-foundry-mcp-key", "FOUNDRY_LOCAL_KEY": "dev-foundry-key"}),
        ("portal", "clients/portal-dev", "server:app", portal,
         {"PORTAL_ISSUER": url(portal), "BROKER_URL": url(broker), "DIRECTLINE_DOMAIN": f"{url(relay)}/v3/directline"}),
    ]
    return [{"name": n, "cwd": ROOT / d, "app": a, "port": p, "url": url(p), "env": {**os.environ, **common, **e}} for n, d, a, p, e in rows]


def _healthy(url: str) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=1) as resp:
            return resp.status < 500
    except Exception:  # noqa: BLE001
        return False


@contextlib.contextmanager
def running(base: int = 8100, quiet: bool = False) -> Iterator[dict[str, str]]:
    procs: list[subprocess.Popen] = []
    services = plan(base)
    try:
        for s in services:
            out = subprocess.DEVNULL if quiet else None
            procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", s["app"], "--host", "127.0.0.1", "--port", str(s["port"]), "--log-level", "warning"],
                                          cwd=s["cwd"], env=s["env"], stdout=out, stderr=out))
        deadline = time.time() + 30
        for s in services:
            path = "/" if s["name"] == "portal" else "/healthz"
            while not _healthy(s["url"] + path):
                if time.time() > deadline:
                    raise RuntimeError(f"{s['name']} did not start on {s['url']}")
                time.sleep(0.2)
        yield {s["name"]: s["url"] for s in services}
    finally:
        for p in procs:
            p.send_signal(signal.SIGINT)
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", type=int, default=8100)
    args = ap.parse_args()
    with running(args.base) as urls:
        print("\nHealthGen local stack is up:")
        for name, u in urls.items():
            print(f"  {name:8s} {u}")
        print(f"\nOpen {urls['portal']} (switch users in the header). Ctrl-C to stop.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
