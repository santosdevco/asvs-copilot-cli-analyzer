"""
analyzers/git.py — Git repository metadata (branch, contributors, hot files).
"""
from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Optional


def _git(args: list[str], cwd: Path) -> Optional[str]:
    try:
        r = subprocess.run(
            ["git"] + args, cwd=str(cwd),
            capture_output=True, text=True, timeout=15,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def analyze_git(root: Path) -> dict:
    if not (root / ".git").exists():
        return {"available": False}

    branch          = _git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    last_commit     = _git(["log", "-1", "--format=%H %s %ad", "--date=short"], root)
    remote          = _git(["remote", "get-url", "origin"], root)
    total_raw       = _git(["rev-list", "--count", "HEAD"], root)

    # Hot files (last 1000 commits)
    raw_files = _git(
        ["log", "--pretty=format:", "--name-only", "--diff-filter=ACDM", "-n", "1000"],
        root,
    )
    file_activity: Counter = Counter()
    if raw_files:
        for line in raw_files.splitlines():
            if line.strip():
                file_activity[line.strip()] += 1

    most_active = [
        {"file": f, "commits": c}
        for f, c in file_activity.most_common(15)
    ]

    # Recently modified (last 14 days)
    recent_raw = _git(
        ["log", "--since=14.days", "--pretty=format:", "--name-only", "--diff-filter=ACDM"],
        root,
    )
    recently_modified: list[str] = []
    if recent_raw:
        seen: set[str] = set()
        for line in recent_raw.splitlines():
            if line.strip() and line.strip() not in seen:
                seen.add(line.strip())
                recently_modified.append(line.strip())

    # Contributors
    contrib_raw = _git(["shortlog", "-s", "-n", "--no-merges"], root)
    contributors = []
    if contrib_raw:
        for line in contrib_raw.splitlines()[:10]:
            m = re.match(r"\s*(\d+)\s+(.+)", line)
            if m:
                contributors.append({"commits": int(m.group(1)), "author": m.group(2).strip()})

    first_commit_date = _git(["log", "--reverse", "--format=%ad", "--date=short", "-1"], root)

    return {
        "available":               True,
        "branch":                  branch,
        "last_commit":             last_commit,
        "first_commit_date":       first_commit_date,
        "remote":                  remote,
        "total_commits":           int(total_raw) if total_raw and total_raw.isdigit() else None,
        "most_active_files":       most_active,
        "recently_modified_files": recently_modified[:20],
        "top_contributors":        contributors,
    }
