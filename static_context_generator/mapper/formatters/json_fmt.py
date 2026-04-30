"""
formatters/json_fmt.py — JSON and compact-JSON output formatters.
"""
from __future__ import annotations

import copy
import json


def format_json(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


def format_json_compact(data: dict) -> str:
    """Compact JSON: strips per-file details and full tree children for LLM injection."""
    compact = copy.deepcopy(data)
    compact["code_signals"].pop("per_file", None)

    def strip_tree_children(node: dict, depth: int = 0) -> None:
        if depth >= 2 and node["type"] == "directory":
            node.pop("children", None)
            return
        for child in node.get("children", []):
            strip_tree_children(child, depth + 1)

    strip_tree_children(compact["structure"].get("tree", {}))
    compact["imports"].pop("graph", None)
    return json.dumps(compact, indent=2, ensure_ascii=False, default=str)
