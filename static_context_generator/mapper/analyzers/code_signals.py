"""
analyzers/code_signals.py — Code metrics and multi-language security signals.

Uses RuleEngine for language-agnostic security analysis. Falls back gracefully
when a language has no registered rules.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from ..core.config import (
    NON_CODE_LANGS, FUNCTION_PATTERNS, CLASS_PATTERNS, TODO_PATTERN,
)
from ..core.fs import detect_language, read_text, count_lines
from ..rules import RULE_ENGINE


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sig_weight(entry: dict) -> int:
    sig = entry.get("security_signals", {})
    score = 0
    score += len(sig.get("sinks", [])) * 3
    score += len(sig.get("sqli_hints", [])) * 5
    score += 3 if sig.get("authz_gap") else 0
    score += 3 if sig.get("missing_input_validation") else 0
    score += len(sig.get("jwt_issues", [])) * 2
    score += len(sig.get("error_leaks", [])) * 2
    score += len(sig.get("sensitive_fields", [])) * 2
    score += sum(sig.get("sources", {}).values())
    score += len(sig.get("crypto", []))
    score += len(sig.get("todos", []))
    return score


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def analyze_code_signals(files: list[Path], root: Path) -> dict:
    per_file: list[dict] = []
    totals: Counter = Counter()

    for f in files:
        lang = detect_language(f)
        text = read_text(f)
        if not text:
            continue

        lines = count_lines(text)
        size = f.stat().st_size
        todo_hits = Counter(TODO_PATTERN.findall(text))

        func_count = 0
        class_count = 0
        if lang in FUNCTION_PATTERNS:
            func_count = len(FUNCTION_PATTERNS[lang].findall(text))
        if lang in CLASS_PATTERNS:
            class_count = len(CLASS_PATTERNS[lang].findall(text))

        complexity_keywords = len(re.findall(
            r"\b(if|else|elif|for|while|case|catch|except|and|or|&&|\|\|)\b",
            text,
        ))

        # Security signals — RuleEngine dispatches to the right language rules
        sec_signals: dict = {}
        if lang and RULE_ENGINE.supports(lang):
            sec_signals = RULE_ENGINE.scan(text, lang)

        entry: dict = {
            "path":                str(f.relative_to(root)),
            "lang":                lang,
            "lines":               lines,
            "bytes":               size,
            "functions":           func_count,
            "classes":             class_count,
            "complexity_keywords": complexity_keywords,
            "todos":               dict(todo_hits),
        }
        if sec_signals:
            entry["security_signals"] = sec_signals

        per_file.append(entry)

        totals["functions"] += func_count
        totals["classes"]   += class_count
        for k, v in todo_hits.items():
            totals[k] += v

    # ── Aggregates ────────────────────────────────────────────────────────
    source_files = [f for f in per_file if f["lang"] not in {*NON_CODE_LANGS, None}]
    largest = sorted(source_files, key=lambda x: x["lines"], reverse=True)[:10]
    most_complex = sorted(
        [f for f in source_files if f["functions"] > 0],
        key=lambda x: x["functions"],
        reverse=True,
    )[:10]
    todo_heavy = sorted(
        [f for f in per_file if f["todos"]],
        key=lambda x: sum(x["todos"].values()),
        reverse=True,
    )[:10]

    security_heatmap = sorted(
        [f for f in per_file if f.get("security_signals")],
        key=_sig_weight,
        reverse=True,
    )[:20]

    return {
        "totals": dict(totals),
        "per_file": per_file,
        "largest_files": [
            {"path": f["path"], "lines": f["lines"], "lang": f["lang"]}
            for f in largest
        ],
        "most_complex_files": [
            {
                "path": f["path"],
                "functions": f["functions"],
                "classes": f["classes"],
                "complexity_keywords": f["complexity_keywords"],
            }
            for f in most_complex
        ],
        "todo_heavy_files": [
            {"path": f["path"], "todos": f["todos"]}
            for f in todo_heavy
        ],
        "security_heatmap": [
            {
                "path": f["path"],
                "score": _sig_weight(f),
                "signals": list(f.get("security_signals", {}).keys()),
            }
            for f in security_heatmap
        ],
    }
