#!/usr/bin/env python3
"""Maintain the per-file technical documentation.

    python docs/technical/build_index.py          # rebuild the file index, fix links, check coverage
    python docs/technical/build_index.py --check  # fail if any file lacks a page or a link is broken (CI)

* Every tracked file needs a page at docs/technical/files/<path>.md, starting with "# `<path>`" and a
  "> **Summary:** …" line.
* "{{T}}" in a page is replaced by the relative path to docs/technical/ (write links as {{T}}sequences.md).
* A "Source:" link to the file is added under the heading.
* The index table in docs/technical/README.md (between the FILE-INDEX markers) is regenerated.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TECH = ROOT / "docs" / "technical"
FILES = TECH / "files"
SKIP = ("docs/technical/",)
AREAS = [
    ("services/agent-relay/", "Agent relay"),
    ("services/identity-broker/", "Identity broker"),
    ("services/mcp-healthgen/", "MCP data spoke"),
    ("services/healthgen-core-mock/", "HealthGen core mock"),
    ("services/foundry-local/", "Foundry and APIM local stand-in"),
    ("agents/", "Foundry agents"),
    ("search/", "Plan documents and search"),
    ("apim/", "API Management"),
    ("handoff/", "Hand-off"),
    ("clients/", "Portal stand-in"),
    ("scripts/", "Scripts"),
    ("tests/", "End-to-end tests"),
    ("libs/", "Test helpers"),
    ("docs/", "Design documents"),
    ("", "Repository root"),
]
LINK = re.compile(r"\]\(([^)\s]+)\)")


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    return sorted(p for p in out.splitlines() if p and not p.startswith(SKIP))


def page_for(path: str) -> Path:
    return FILES / f"{path}.md"


def anchors(md: Path) -> set[str]:
    out = set()
    for line in md.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            text = line.lstrip("#").strip().lower()
            text = re.sub(r"[^\w\- ]", "", text).replace(" ", "-")
            out.add(text)
    return out


def fix_page(path: str, page: Path) -> str:
    text = page.read_text(encoding="utf-8")
    to_tech = os.path.relpath(TECH, page.parent).replace(os.sep, "/") + "/"
    text = text.replace("{{T}}", to_tech)
    source = os.path.relpath(ROOT / path, page.parent).replace(os.sep, "/")
    if "\nSource: " not in text:
        lines = text.split("\n", 1)
        text = f"{lines[0]}\n\nSource: [`{path}`]({source})\n" + (lines[1] if len(lines) > 1 else "")
    page.write_text(text, encoding="utf-8")
    m = re.search(r"> \*\*Summary:\*\* (.+)", text)
    return m.group(1).strip() if m else ""


def check_links(md_files: list[Path]) -> list[str]:
    broken = []
    for md in md_files:
        for target in LINK.findall(md.read_text(encoding="utf-8")):
            if re.match(r"^[a-z]+:", target):
                continue
            path, _, frag = target.partition("#")
            dest = (md.parent / path).resolve() if path else md
            if not dest.exists():
                broken.append(f"{md.relative_to(ROOT)} → {target}")
            elif frag and dest.suffix == ".md" and frag not in anchors(dest):
                broken.append(f"{md.relative_to(ROOT)} → {target} (anchor)")
    return broken


def main() -> int:
    check_only = "--check" in sys.argv
    files = tracked()
    missing = [p for p in files if not page_for(p).exists()]
    rows: dict[str, list[str]] = {title: [] for _, title in AREAS}
    for path in files:
        if path in missing:
            continue
        summary = fix_page(path, page_for(path)) if not check_only else re.search(r"> \*\*Summary:\*\* (.+)", page_for(path).read_text()).group(1)
        summary = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", summary)  # page-relative links don't work in the index
        area = next(title for prefix, title in AREAS if path.startswith(prefix))
        link = os.path.relpath(page_for(path), TECH).replace(os.sep, "/")
        rows[area].append(f"| [`{path}`]({link}) | {summary} |")
    table = []
    for _, title in AREAS:
        if rows[title]:
            table += [f"\n### {title}\n", "| File | What it does |", "| --- | --- |", *rows[title]]
    readme = TECH / "README.md"
    text = readme.read_text(encoding="utf-8")
    new = re.sub(r"(<!-- FILE-INDEX:START -->).*(<!-- FILE-INDEX:END -->)", lambda m: m.group(1) + "\n" + "\n".join(table) + "\n" + m.group(2), text, flags=re.S)
    if not check_only:
        readme.write_text(new, encoding="utf-8")
    orphans = [str(p.relative_to(FILES))[:-3] for p in FILES.rglob("*.md") if str(p.relative_to(FILES))[:-3] not in files]
    broken = check_links([readme, TECH / "sequences.md", *FILES.rglob("*.md")])
    print(f"{len(files)} files, {len(files) - len(missing)} pages")
    for label, items in (("missing page", missing), ("orphan page", orphans), ("broken link", broken)):
        for item in items:
            print(f"  {label}: {item}")
    if check_only and new != text:
        print("  index out of date: run without --check")
        return 1
    return 1 if (missing or orphans or broken) else 0


if __name__ == "__main__":
    sys.exit(main())
