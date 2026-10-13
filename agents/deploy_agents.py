#!/usr/bin/env python3
"""Deploy the declarative HealthGen agents (agents/*.yaml) and their project connections to Microsoft Foundry.

    python agents/deploy_agents.py --env-file agents/foundry.env --dry-run   # print resolved requests
    python agents/deploy_agents.py --env-file agents/foundry.env             # apply

Order: project connections → specialist agents (new version each run) → enable incoming A2A on specialists →
triage agent. Tokens come from the Azure CLI (``az login`` first) unless FOUNDRY_TOKEN / ARM_TOKEN are set.

Placeholders in YAML:  ${VAR} environment value · ${conn:NAME} project connection id · {{> partial}} text from
agents/partials/<partial>.md (inside instructions).

Needs Python 3.10+ and PyYAML only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
API_VERSION = os.getenv("FOUNDRY_API_VERSION", "v1")
ARM_CONNECTIONS_API = "2025-04-01-preview"
ORDER = ["plan-faq.yaml", "benefit-check.yaml", "triage.yaml"]
REQUIRED = ["SUBSCRIPTION_ID", "RESOURCE_GROUP", "FOUNDRY_ACCOUNT", "FOUNDRY_PROJECT", "MODEL_DEPLOYMENT",
            "MCP_SERVER_URL", "MCP_AUDIENCE", "SEARCH_SERVICE_NAME", "SEARCH_INDEX_NAME"]
DOCS_A2A = "https://learn.microsoft.com/azure/foundry/agents/how-to/enable-agent-to-agent-endpoint"


class DeployError(Exception):
    pass


def load_env_file(path: str | None) -> dict[str, str]:
    env = dict(os.environ)
    if path:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        raise DeployError(f"Missing settings: {', '.join(missing)}")
    env.setdefault("PROJECT_ENDPOINT", f"https://{env['FOUNDRY_ACCOUNT']}.services.ai.azure.com/api/projects/{env['FOUNDRY_PROJECT']}")
    return env


def connection_id(env: dict[str, str], name: str) -> str:
    return (f"/subscriptions/{env['SUBSCRIPTION_ID']}/resourceGroups/{env['RESOURCE_GROUP']}/providers/Microsoft.CognitiveServices"
            f"/accounts/{env['FOUNDRY_ACCOUNT']}/projects/{env['FOUNDRY_PROJECT']}/connections/{name}")


_VAR = re.compile(r"\$\{(conn:)?([A-Za-z0-9_.-]+)\}")
_PARTIAL = re.compile(r"\{\{>\s*([a-z0-9_-]+)\s*\}\}")


def resolve(node: Any, env: dict[str, str]) -> Any:
    if isinstance(node, dict):
        return {k: resolve(v, env) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve(v, env) for v in node]
    if not isinstance(node, str):
        return node

    def partial(m: re.Match[str]) -> str:
        path = HERE / "partials" / f"{m.group(1)}.md"
        if not path.exists():
            raise DeployError(f"Unknown partial {m.group(1)}")
        return path.read_text(encoding="utf-8").strip()

    def var(m: re.Match[str]) -> str:
        if m.group(1):
            return connection_id(env, m.group(2))
        if m.group(2) not in env:
            raise DeployError(f"Unresolved ${{{m.group(2)}}}")
        return env[m.group(2)]

    return _VAR.sub(var, _PARTIAL.sub(partial, node))


class Http:
    def __init__(self, env: dict[str, str], dry_run: bool):
        self.env = env
        self.dry_run = dry_run
        self._tokens: dict[str, str] = {}

    def token(self, resource: str) -> str:
        override = self.env.get("ARM_TOKEN" if "management" in resource else "FOUNDRY_TOKEN")
        if override:
            return override
        if resource not in self._tokens:
            try:
                out = subprocess.run(["az", "account", "get-access-token", "--resource", resource, "--query", "accessToken", "-o", "tsv"],
                                     check=True, capture_output=True, text=True)
            except (OSError, subprocess.CalledProcessError) as exc:
                raise DeployError(f"Could not get a token for {resource}; run `az login`. ({exc})") from exc
            self._tokens[resource] = out.stdout.strip()
        return self._tokens[resource]

    def call(self, method: str, url: str, resource: str, body: Any = None, content_type: str = "application/json", ok404: bool = False) -> Any:
        if self.dry_run:
            print(f"\n{method} {url}")
            if body is not None:
                print(json.dumps(body, indent=2)[:6000])
            return {} if method != "GET" else None
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={"Authorization": f"Bearer {self.token(resource)}", "Content-Type": content_type})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and ok404:
                return None
            detail = exc.read().decode(errors="replace")[:1500]
            raise DeployError(f"{method} {url} -> {exc.code}: {detail}") from exc


def deploy_connections(http: Http, env: dict[str, str]) -> None:
    spec = yaml.safe_load((HERE / "connections.yaml").read_text(encoding="utf-8"))
    for conn in spec["connections"]:
        url = f"https://management.azure.com{connection_id(env, conn['name'])}?api-version={ARM_CONNECTIONS_API}"
        http.call("PUT", url, "https://management.azure.com", {"properties": resolve(conn["properties"], env)})
        print(f"✓ connection {conn['name']}")


def agent_body(spec: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    body = {"definition": resolve(spec["definition"], env), "description": spec.get("description", ""), "metadata": spec.get("metadata", {})}
    leftovers = _VAR.findall(json.dumps(body)) + _PARTIAL.findall(json.dumps(body))
    if leftovers:
        raise DeployError(f"Unresolved placeholders in {spec['name']}: {leftovers}")
    return body


def deploy_agent(http: Http, env: dict[str, str], spec: dict[str, Any]) -> None:
    pe, name = env["PROJECT_ENDPOINT"], spec["name"]
    body = agent_body(spec, env)
    existing = None if http.dry_run else http.call("GET", f"{pe}/agents/{name}?api-version={API_VERSION}", "https://ai.azure.com", ok404=True)
    if existing:
        res = http.call("POST", f"{pe}/agents/{name}/versions?api-version={API_VERSION}", "https://ai.azure.com", body)
    else:
        res = http.call("POST", f"{pe}/agents?api-version={API_VERSION}", "https://ai.azure.com", {"name": name, **body})
    version = (res or {}).get("version") or ((res or {}).get("versions") or {}).get("latest", {}).get("version")
    print(f"✓ agent {name}" + (f" version {version}" if version else ""))

    a2a = spec.get("a2a") or {}
    if a2a.get("enabled"):
        patch = a2a.get("enable_body") or {
            "agent_endpoint": {"protocol_configuration": {"responses": {}, "a2a": {}}},
            "agent_card": a2a.get("agent_card", {}),
        }
        try:
            http.call("PATCH", f"{pe}/agents/{name}?api-version={API_VERSION}", "https://ai.azure.com", resolve(patch, env), "application/merge-patch+json")
            print(f"✓ incoming A2A enabled on {name}")
            if not http.dry_run:
                card = http.call("GET", f"{pe}/agents/{name}/endpoint/protocols/a2a/agentCard/v1.0", "https://ai.azure.com", ok404=True)
                print(f"  agent card: {'served' if card else 'NOT served yet'}")
        except DeployError as exc:
            print(f"! Enabling A2A on {name} failed. Check the PATCH body against {DOCS_A2A} and set a2a.enable_body in {name}'s YAML.\n  {exc}", file=sys.stderr)
            raise


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-connections", action="store_true")
    ap.add_argument("--only", nargs="*", help="agent names to deploy, e.g. healthgen-triage")
    args = ap.parse_args(argv)
    try:
        env = load_env_file(args.env_file)
        http = Http(env, args.dry_run)
        if not args.skip_connections:
            deploy_connections(http, env)
        for file in ORDER:
            spec = yaml.safe_load((HERE / file).read_text(encoding="utf-8"))
            if args.only and spec["name"] not in args.only:
                continue
            deploy_agent(http, env, spec)
    except DeployError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print("\nNext: grant the triage agent identity 'Foundry Agent Consumer' on the project (see docs/deployment-runbook.md, step 7).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
