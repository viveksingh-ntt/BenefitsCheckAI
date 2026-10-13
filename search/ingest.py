#!/usr/bin/env python3
"""Create the plan-documents index in Azure AI Search and upload the synthetic documents, one chunk per section.

    export SEARCH_SERVICE_NAME=srch-healthgen
    az login                                   # uses an Entra token (needs Search Service Contributor + Index Data Contributor)
    python search/ingest.py                    # or set SEARCH_ADMIN_KEY to use a key
    python search/ingest.py --dry-run          # print the chunks only

Stdlib + PyYAML. Re-running is safe: the index is created or updated and documents are merged by id.
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

import yaml

HERE = Path(__file__).resolve().parent
API = "2024-07-01"
PORTAL_DOCS_BASE = os.getenv("PLAN_DOCS_BASE_URL", "https://members.healthgen.example/plan-documents")


def chunks(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    _, front, body = text.split("---", 2)
    meta = yaml.safe_load(front)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    out = []
    for i, part in enumerate(re.split(r"^# ", body, flags=re.M)[1:]):
        section, _, content = part.partition("\n")
        out.append({
            "@search.action": "mergeOrUpload",
            "id": f"{path.stem}-{i:02d}",
            "title": meta["title"],
            "section": section.strip(),
            "content": " ".join(content.split()),
            "plan": meta["plan"],
            "plan_ref": meta["plan_ref"],
            "doc_type": meta["doc_type"],
            "url": f"{PORTAL_DOCS_BASE}/{path.stem}#{re.sub(r'[^a-z0-9]+', '-', section.lower()).strip('-')}",
        })
    return out


def headers() -> dict[str, str]:
    key = os.getenv("SEARCH_ADMIN_KEY")
    if key:
        return {"api-key": key, "Content-Type": "application/json"}
    token = subprocess.run(["az", "account", "get-access-token", "--resource", "https://search.azure.com", "--query", "accessToken", "-o", "tsv"],
                           check=True, capture_output=True, text=True).stdout.strip()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def call(method: str, url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method=method, headers=headers())
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        sys.exit(f"{method} {url} -> {exc.code}: {exc.read().decode(errors='replace')[:800]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    index = json.loads((HERE / "index.json").read_text(encoding="utf-8"))
    index["name"] = os.getenv("SEARCH_INDEX_NAME", index["name"])
    docs = [c for p in sorted((HERE / "documents").glob("*.md")) for c in chunks(p)]
    if args.dry_run:
        print(json.dumps(docs, indent=2))
        print(f"{len(docs)} chunks", file=sys.stderr)
        return
    base = f"https://{os.environ['SEARCH_SERVICE_NAME']}.search.windows.net"
    call("PUT", f"{base}/indexes/{index['name']}?api-version={API}", index)
    print(f"✓ index {index['name']}")
    result = call("POST", f"{base}/indexes/{index['name']}/docs/index?api-version={API}", {"value": docs})
    failed = [r for r in result.get("value", []) if not r.get("status")]
    print(f"✓ uploaded {len(docs) - len(failed)} chunks" + (f", {len(failed)} failed" if failed else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
