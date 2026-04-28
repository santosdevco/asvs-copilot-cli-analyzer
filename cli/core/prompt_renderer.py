"""
prompt_renderer.py
──────────────────
Replaces {{key}} placeholders in a prompt template string with values from a
context dict.  Supports dot-notation keys (e.g. {{component.id}}) but plain
snake_case keys are the common case.
"""
from __future__ import annotations

import re
from typing import Any, Dict

# Matches {{key}} or {{key.sub}} — greedy-safe, no nested braces
_PLACEHOLDER_RE = re.compile(r"\{\{([\w.]+)\}\}")


def render(template: str, context: Dict[str, Any]) -> str:
    """Return *template* with every {{key}} replaced by context[key].

    Unknown keys are left as-is so callers can detect missing values.
    """
    def _replace(match: re.Match) -> str:
        key = match.group(1)
        value = context.get(key)
        if value is None:
            return match.group(0)          # keep original placeholder
        return str(value)

    return _PLACEHOLDER_RE.sub(_replace, template)


def missing_keys(template: str, context: Dict[str, Any]) -> list[str]:
    """Return list of placeholder keys present in *template* but absent from *context*."""
    keys = _PLACEHOLDER_RE.findall(template)
    return [k for k in keys if k not in context]
