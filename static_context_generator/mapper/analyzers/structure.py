"""
analyzers/structure.py — Directory tree builder and language distribution.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

from ..core.config import NON_CODE_LANGS
from ..core.fs import (
    is_excluded_dir, is_excluded_file,
    detect_language, read_text, count_lines, fmt_bytes,
)


def build_tree(
    root: Path,
    exclude_locks: bool,
    max_depth: Optional[int],
    depth: int = 0,
) -> dict:
    node: dict = {
        "name": root.name or str(root),
        "type": "directory",
        "children": [],
        "summary": {"files": 0, "bytes": 0, "lines": 0},
    }
    if max_depth is not None and depth >= max_depth:
        node["truncated"] = True
        return node
    try:
        entries = sorted(root.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    except PermissionError:
        node["error"] = "permission denied"
        return node

    for entry in entries:
        if entry.is_symlink():
            continue
        if entry.is_dir():
            if is_excluded_dir(entry.name):
                continue
            child = build_tree(entry, exclude_locks, max_depth, depth + 1)
            node["children"].append(child)
            for k in ("files", "bytes", "lines"):
                node["summary"][k] += child["summary"][k]
        elif entry.is_file():
            if is_excluded_file(entry, exclude_locks):
                continue
            size = entry.stat().st_size
            text = read_text(entry)
            lines = count_lines(text) if text is not None else None
            node["children"].append({
                "name": entry.name,
                "type": "file",
                "lang": detect_language(entry),
                "bytes": size,
                "lines": lines,
            })
            node["summary"]["files"] += 1
            node["summary"]["bytes"] += size
            if lines:
                node["summary"]["lines"] += lines
    return node


def analyze_languages(files: list[Path]) -> dict:
    stats: dict[str, dict] = defaultdict(lambda: {"files": 0, "lines": 0, "bytes": 0})
    for f in files:
        lang = detect_language(f) or "Other"
        text = read_text(f)
        stats[lang]["files"] += 1
        stats[lang]["bytes"] += f.stat().st_size
        stats[lang]["lines"] += count_lines(text) if text else 0

    total_lines = sum(v["lines"] for v in stats.values()) or 1
    distribution = {
        lang: {**s, "pct_lines": round(s["lines"] / total_lines * 100, 1)}
        for lang, s in sorted(stats.items(), key=lambda x: -x[1]["lines"])
    }

    code_only = {k: v for k, v in distribution.items() if k not in NON_CODE_LANGS}
    primary = (
        max(code_only, key=lambda k: code_only[k]["lines"])
        if code_only
        else (max(distribution, key=lambda k: distribution[k]["lines"]) if distribution else "Unknown")
    )
    return {"primary": primary, "distribution": distribution}
