#!/usr/bin/env python3
"""Check whether the published skills are older than the docs they derive from.

The skills under skills/ are derived from the authoritative docs. This script
compares the newest commit touching each authoritative doc against the commit
recorded for that path in skills/.skill-source.json.

Usage:
    python tools/skill_drift_check.py            # compare against local git
    python tools/skill_drift_check.py --remote   # compare against GitHub main
    python tools/skill_drift_check.py --update   # record current commits

Exit codes: 0 up to date, 3 drift, 1 cannot check.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKER = ROOT / "skills" / ".skill-source.json"


def load_marker() -> dict:
    return json.loads(MARKER.read_text(encoding="utf-8"))


def local_last_commit(path: str) -> tuple[str, str]:
    out = subprocess.run(
        ["git", "log", "-1", "--format=%H%x00%s", "--", path],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    sha, _, msg = out.stdout.strip().partition("\x00")
    return sha, msg


def remote_last_commit(repo: str, path: str) -> tuple[str, str]:
    query = urllib.parse.urlencode({"path": path, "per_page": 1})
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/commits?{query}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "skill-drift-check"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    if not data:
        return "", ""
    return data[0]["sha"], data[0]["commit"]["message"].splitlines()[0]


def main() -> int:
    marker = load_marker()
    repo = marker["repo"]
    recorded: dict[str, str] = marker["docs_commits"]
    remote = "--remote" in sys.argv

    latest: list[tuple[str, str, str]] = []
    for path in marker["authoritative_paths"]:
        sha, msg = remote_last_commit(repo, path) if remote else local_last_commit(path)
        latest.append((path, sha, msg))

    if "--update" in sys.argv:
        marker["docs_commits"] = {path: sha for path, sha, _ in latest}
        MARKER.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for path, sha, _ in latest:
            print(f"recorded {sha[:12]}  {path}")
        return 0

    drifted = []
    for path, sha, msg in latest:
        old = recorded.get(path, "")
        if sha != old:
            drifted.append((path, sha, msg))
            print(f"DRIFT {sha[:12]}  {path}  {msg}")
        else:
            print(f"ok    {sha[:12]}  {path}")

    if not drifted:
        print("skills 与文档同源。")
        return 0

    print("\n文档已变，skills/ 需要重新派生：")
    print("  1. 按 docs/ 的改动更新 skills/*/SKILL.md 与账号里的同名技能")
    print("  2. python tools/skill_drift_check.py --update")
    print("  3. 把 skills/ 与 .skill-source.json 提交到同一个 commit")
    return 3


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"无法检查：{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
