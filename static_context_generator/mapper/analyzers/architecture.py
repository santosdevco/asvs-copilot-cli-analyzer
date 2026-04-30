"""
analyzers/architecture.py — Project structure & type classification.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from ..core.config import SEMANTIC_FOLDERS, ENTRY_POINT_NAMES, INFRA_FILE_PATTERNS
from ..core.fs import is_excluded_dir


def analyze_architecture(root: Path, files: list[Path]) -> dict:
    rel_files = [f.relative_to(root) for f in files]

    # Entry points
    entry_points = [str(rf) for rf in rel_files if rf.name in ENTRY_POINT_NAMES]

    # Top-2-level directory names for semantic detection
    all_dir_names: set[str] = set()
    for dp, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if not is_excluded_dir(d)]
        rel_dp = Path(dp).relative_to(root)
        if len(rel_dp.parts) < 2:
            for d in dirnames:
                all_dir_names.add(d.lower())

    semantic = sorted(all_dir_names & SEMANTIC_FOLDERS)

    # Infrastructure files
    infra = [pattern for pattern in INFRA_FILE_PATTERNS if (root / pattern).exists()]

    # Test files
    test_files = [
        f for f in files
        if re.search(r"(test|spec|_test|\.test\.|\.spec\.)", f.name, re.I)
        or any(
            part.lower() in {"tests", "test", "__tests__", "spec", "specs"}
            for part in f.relative_to(root).parts
        )
    ]
    total = len(files)
    test_count = len(test_files)

    # Project type heuristic
    names = {f.name.lower() for f in files}
    proj_type = "unknown"
    if "manage.py" in names or any(f.name == "wsgi.py" for f in files):
        proj_type = "web_api"
    elif "index.js" in names or "index.ts" in names:
        proj_type = "web_api" if any(d in semantic for d in ("routes", "controllers", "handlers")) else "frontend"
    elif "main.go" in names:
        proj_type = "service"
    elif "app.py" in names or "server.py" in names:
        proj_type = "web_api"
    elif any("cli" in str(f).lower() or "commands" in str(f).lower() for f in files):
        proj_type = "cli"

    # Monorepo heuristic
    if sum(1 for f in files if f.name == "package.json") > 2 or \
       sum(1 for f in files if f.name == "pyproject.toml") > 2:
        proj_type = "monorepo"

    return {
        "type": proj_type,
        "entry_points": list(dict.fromkeys(entry_points)),
        "semantic_folders": semantic,
        "infrastructure_files": infra,
        "test_files_count": test_count,
        "source_files_count": total - test_count,
        "test_ratio": round(test_count / total, 2) if total else 0,
    }
