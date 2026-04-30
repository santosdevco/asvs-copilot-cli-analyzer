"""
formatters/sections/code_signals.py — TXT formatter for the code_signals section.
"""
from __future__ import annotations

from ..base import _txt_header


def _one_line(value: object) -> str:
    return " ".join(str(value).split())


def format_code_signals_txt(section: dict, meta: dict) -> str:
    cs  = section
    SEP = "─" * 68
    lines: list[str] = _txt_header("CODE SIGNALS — SECURITY HEATMAP", meta)

    tot = cs.get("totals", {})
    hm  = cs.get("security_heatmap", [])
    pf  = {e["path"]: e for e in cs.get("per_file", [])}

    lines += [
        f"Total functions : {tot.get('functions', 0)}  "
        f"classes: {tot.get('classes', 0)}  "
        f"TODOs: {tot.get('TODO', 0) + tot.get('FIXME', 0)}",
        f"Files with signals: {len(hm)}",
        "",
        "Score legend: sinks×3  sqli×4  authz_gap×3  err_leak×2  source×1  crypto×1  todo×1",
        "",
    ]

    lines += [SEP, "[SECURITY HEATMAP — top files by risk score]", SEP]
    lines.append(f"  {'SCORE':>5}  {'FILE':<48}  SIGNALS PRESENT")
    lines.append("  " + "─" * 90)
    for item in hm:
        sigs = ", ".join(item.get("signals", []))
        lines.append(f"  {item['score']:>5}  {item['path']:<48}  {sigs}")
    lines.append("")

    lines += [SEP, "[PER-FILE SIGNAL DETAIL — ONE LINE PER FILE]", SEP]
    for item in hm:
        fpath  = item["path"]
        fentry = pf.get(fpath, {})
        sig    = fentry.get("security_signals", {})
        score  = item["score"]
        flines = fentry.get("lines", "?")
        cx     = fentry.get("complexity_keywords", 0)

        segments: list[str] = [
            f"FILE: {_one_line(fpath)}",
            f"META: {flines} lines, cx={cx}, score={score}",
        ]

        todos = sig.get("todos") or []
        if todos:
            todo_parts = [f"{t['type']}:{_one_line(t['text'])}" for t in todos]
            segments.append(f"TODOS: {', '.join(todo_parts)}")

        sinks = sig.get("sinks") or []
        if sinks:
            segments.append(f"SINKS: {', '.join(_one_line(s) for s in sinks)}")

        sources = sig.get("sources") or {}
        if sources:
            source_parts = [f"{_one_line(k)}×{v}" for k, v in sources.items()]
            segments.append(f"SOURCES: {', '.join(source_parts)}")

        crypto = sig.get("crypto") or []
        if crypto:
            segments.append(f"CRYPTO: {', '.join(_one_line(c) for c in crypto)}")

        sqli_hints = sig.get("sqli_hints") or []
        if sqli_hints:
            segments.append(f"SQLI_HINTS: {', '.join(_one_line(s) for s in sqli_hints)}")

        if sig.get("authz_gap"):
            segments.append("AUTHZ_GAP: req.params/body.id without visible auth guard")

        error_leaks = sig.get("error_leaks") or []
        if error_leaks:
            segments.append(f"ERROR_LEAKS: {', '.join(_one_line(s) for s in error_leaks)}")

        lines.append(" | ".join(segments))

    lines.append("")

    lines += [SEP, "[LARGEST FILES]", SEP]
    for f in cs.get("largest_files", []):
        lines.append(f"  {f['lines']:>5} lines  {f['path']}")
    lines.append("")

    lines += [SEP, "[MOST COMPLEX FILES]", SEP]
    lines.append(f"  {'FNS':>4}  {'CX':>4}  FILE")
    for f in cs.get("most_complex_files", []):
        lines.append(f"  {f['functions']:>4}  {f['complexity_keywords']:>4}  {f['path']}")
    lines.append("")

    return "\n".join(lines)
