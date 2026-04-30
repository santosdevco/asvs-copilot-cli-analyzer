"""
formatters/sections/middlewares.py — TXT formatter for the middlewares section.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from ..base import _txt_header


def format_middlewares_txt(section: dict, meta: dict) -> str:
    mw  = section
    SEP = "─" * 68
    lines: list[str] = _txt_header("MIDDLEWARE CONTEXT", meta)

    src_files = mw.get("middleware_source_files", [])
    routes    = mw.get("routes_with_middleware", [])

    lines += [
        f"Middleware source files  : {len(src_files)}",
        f"Routes with middleware   : {len(routes)}",
        "",
    ]

    if src_files:
        lines += [SEP, "[MIDDLEWARE SOURCE FILES]", SEP]
        for f in src_files:
            lines.append(f"  {f}")
        lines.append("")

    if routes:
        lines += [SEP, "[ROUTE → MIDDLEWARE CHAIN]", SEP]
        lines.append(f"  {'METHOD':<7} {'PATH':<45} {'FILE':<30} LINE  HANDLER")
        lines.append("  " + "─" * 120)

        by_file: dict = defaultdict(list)
        for r in routes:
            by_file[r.get("file", "?")].append(r)

        for fpath, froutes in sorted(by_file.items()):
            lines.append(f"\n  File: {fpath}")
            for r in froutes:
                method  = r.get("method", "?")
                path    = r.get("path", "?")
                lineno  = r.get("line", "?")
                handler = r.get("handler", "?")
                raw_mw  = r.get("middlewares", [])

                clean: list[str] = []
                for token in raw_mw:
                    t = token.replace("\n", " ").strip()
                    if t in ("[", "]", "(", ")", ""):
                        continue
                    if len(t) > 60:
                        t = t[:57] + "…"
                    clean.append(t)

                mw_str = " → ".join(clean) if clean else "—"
                lines.append(f"    {method:<7} {path:<45} line {lineno:<5}  {handler}")
                lines.append(f"           middlewares: {mw_str}")
        lines.append("")

    freq: Counter = Counter()
    for r in routes:
        for token in r.get("middlewares", []):
            t = token.replace("\n", " ").strip()
            if t and t not in ("[", "]"):
                m = re.match(r"(\w+)", t)
                if m:
                    freq[m.group(1)] += 1

    if freq:
        lines += [SEP, "[MIDDLEWARE USAGE FREQUENCY]", SEP]
        for name, count in freq.most_common():
            lines.append(f"  {name:<35} {count:>3}x")
        lines.append("")

    return "\n".join(lines)
