"""
formatters/sections/identity.py — TXT formatter for the identity/project section.
"""
from __future__ import annotations

from ..base import _txt_header


def format_identity_txt(section: dict, meta: dict) -> str:
    idn  = section
    SEP  = "─" * 68
    lines: list[str] = _txt_header("PROJECT IDENTITY", meta)

    lines += [
        f"Project name     : {idn.get('name', '—')}",
        f"Project type     : {idn.get('type', '—')}",
        f"Primary language : {idn.get('primary_language', '—')}",
        f"Frameworks       : {', '.join(idn.get('frameworks', [])) or 'none detected'}",
        "",
    ]

    lines += [SEP, "[LANGUAGE DISTRIBUTION]", SEP]
    lang_dist   = idn.get("language_distribution", {})
    total_lines = sum(v.get("lines", 0) for v in lang_dist.values())
    for lang, stats in lang_dist.items():
        pct   = stats.get("pct_lines", 0.0)
        files = stats.get("files", 0)
        lns   = stats.get("lines", 0)
        kb    = stats.get("bytes", 0) / 1024
        lines.append(
            f"  {lang:<18} {pct:>5.1f}%   {lns:>6} lines   {files:>3} files   {kb:>7.1f} KB"
        )
    lines += [f"  {'TOTAL':<18}        {total_lines:>6} lines", ""]

    deps      = idn.get("dependencies", {})
    src_files = deps.get("source_files", [])
    scripts   = deps.get("npm_scripts", [])
    prod      = deps.get("production", [])
    dev       = deps.get("development", [])

    lines += [SEP, "[DEPENDENCIES]", SEP]
    lines.append(f"  Manifest files : {', '.join(src_files) or '—'}")
    lines.append(f"  Run scripts    : {', '.join(scripts) or '—'}")
    lines.append("")

    if prod:
        lines.append(f"  Production ({len(prod)}):")
        for pkg in prod:
            lines.append(f"    {pkg['name']:<35} {pkg.get('version', '')}")
        lines.append("")

    if dev:
        lines.append(f"  Development ({len(dev)}):")
        for pkg in dev:
            lines.append(f"    {pkg['name']:<35} {pkg.get('version', '')}")
        lines.append("")

    return "\n".join(lines)
