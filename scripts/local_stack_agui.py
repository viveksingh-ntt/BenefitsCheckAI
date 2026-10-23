#!/usr/bin/env python3
"""Run the HealthGen stack locally over AG-UI (no Azure, no Bot Service, no Direct Line).

    python scripts/local_stack_agui.py              # then open http://localhost:8081
    python scripts/local_stack_agui.py --base 9200  # other ports (portal = base - 19)

    8101 healthgen-core-mock   8102 identity-broker (app.main_agui)   8103 mcp-healthgen
    8105 foundry-local         8106 agent relay, AG-UI host (host_agui)
    8081 portal-dev-agui (host page + BFF)

Same services and dev-only keys as scripts/local_stack.py, which stays the Direct Line path; this script only swaps the
broker entry point, replaces the Direct Line emulator with host_agui, and points the portal at /v1/agui/token.
"""

from __future__ import annotations

import argparse
import contextlib
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_stack import ROOT, _healthy, plan as direct_line_plan  # noqa: E402


def plan(base: int = 8100) -> list[dict]:
    rows = {s["name"]: s for s in direct_line_plan(base)}
    broker, relay = rows["broker"]["url"], f"http://localhost:{base + 6}"
    portal_port = 8081 if base == 8100 else base - 19
    portal = f"http://localhost:{portal_port}"

    b = rows["broker"]
    b["app"] = "app.main_agui:app"
    for k in ("DIRECTLINE_SECRET", "DIRECTLINE_ENDPOINT"):
        b["env"].pop(k, None)
    b["env"].update({"DIRECTLINE_TRUSTED_ORIGINS": portal, "PORTAL_ISSUERS": portal, "PORTAL_JWKS_URL": f"{portal}/.well-known/jwks.json"})

    r = rows["relay"]
    r.update(app="host_agui:app", port=base + 6, url=relay)
    for k in ("DIRECTLINE_SECRET", "DEV_CORS_ORIGINS"):
        r["env"].pop(k, None)
    r["env"].update({"BROKER_ISSUER": broker, "BROKER_JWKS_URL": f"{broker}/.well-known/jwks.json", "AGUI_CORS_ORIGINS": portal})

    p = rows["portal"]
    p.update(cwd=ROOT / "clients" / "portal-dev-agui", port=portal_port, url=portal)
    p["env"].pop("DIRECTLINE_DOMAIN", None)
    p["env"].update({"PORTAL_ISSUER": portal, "BROKER_URL": broker, "AGUI_ENDPOINT": f"{relay}/agui"})
    return list(rows.values())


@contextlib.contextmanager
def running(base: int = 8100, quiet: bool = False) -> Iterator[dict[str, str]]:
    procs: list[subprocess.Popen] = []
    services = plan(base)
    try:
        for s in services:
            out = subprocess.DEVNULL if quiet else None
            procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", s["app"], "--host", "127.0.0.1", "--port", str(s["port"]),
                                           "--log-level", "warning", "--timeout-keep-alive", "75"],
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
        print("\nHealthGen local stack (AG-UI) is up:")
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
