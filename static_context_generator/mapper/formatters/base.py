"""
formatters/base.py — Shared helpers used by all formatters.
"""
from __future__ import annotations

from pathlib import Path
from ..core.fs import fmt_bytes


def _txt_header(title: str, meta: dict) -> list[str]:
    W = 68
    return [
        "=" * W,
        f"  {title}",
        f"  Project : {meta.get('root', '')}",
        f"  Generated: {meta.get('generated_at', '')}",
        "=" * W,
        "",
    ]


def _file_list(files: list[str], limit: int = 6) -> str:
    """Compact file list: show up to `limit` basenames, suffix with count."""
    if not files:
        return "—"
    names = [Path(f).name for f in files]
    if len(names) <= limit:
        return ", ".join(names)
    shown = ", ".join(names[:limit])
    return f"{shown} … (+{len(names) - limit} more — {len(names)} total)"


def _render_tree_lines(node: dict, prefix: str = "", is_last: bool = True) -> list[str]:
    connector = "└── " if is_last else "├── "
    extender  = "    " if is_last else "│   "
    out = []
    if node["type"] == "directory":
        s = node["summary"]
        out.append(
            f"{prefix}{connector}{node['name']}/ "
            f"[{s['files']} files | {fmt_bytes(s['bytes'])} | {s['lines']:,} lines]"
        )
        children = node.get("children", [])
        for i, child in enumerate(children):
            out.extend(_render_tree_lines(child, prefix + extender, i == len(children) - 1))
        if node.get("truncated"):
            out.append(f"{prefix}{extender}... (max-depth reached)")
    else:
        ln = f"{node['lines']:,} lines" if node.get("lines") is not None else "binary"
        out.append(f"{prefix}{connector}{node['name']} [{fmt_bytes(node['bytes'])} | {ln}]")
    return out
