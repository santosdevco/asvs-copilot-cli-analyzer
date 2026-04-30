"""
formatters/sections/frontend.py — TXT formatter for the frontend security section.
"""
from __future__ import annotations

from ..base import _txt_header


def _one_line(value: object) -> str:
    return " ".join(str(value).split())


def format_frontend_txt(section: dict, meta: dict) -> str:
    if not section.get("available"):
        note = section.get("_note", "not a frontend project")
        return f"FRONTEND SECURITY: {note}\n"

    SEP = "─" * 68
    lines: list[str] = _txt_header("FRONTEND SECURITY ANALYSIS", meta)

    active_fw  = section.get("active_frameworks", [])
    total_hits = section.get("total_xss_sink_hits", 0)
    csp        = section.get("csp_meta_found", False)
    routes     = section.get("client_routes", [])
    storage    = section.get("storage_sensitive", [])
    postmsg    = section.get("postmessage_no_origin", [])
    critical   = section.get("critical_files", [])
    by_file    = section.get("findings_by_file", {})

    frameworks_str = ", ".join(active_fw) if active_fw else "generic JS/TS"
    lines += [
        f"Frameworks detected : {frameworks_str}",
        f"XSS sink hits       : {total_hits}",
        f"CSP meta tag        : {'PRESENT' if csp else 'MISSING — no Content-Security-Policy meta tag found'}",
        f"Client routes       : {len(routes)}",
        "",
    ]

    # ── Critical files ────────────────────────────────────────────────────
    lines += [SEP, "[CRITICAL FILES — high-severity XSS sinks]", SEP]
    if critical:
        for f in critical:
            lines.append(f"  {f}")
    else:
        lines.append("  None found.")
    lines.append("")

    # ── XSS findings per file ─────────────────────────────────────────────
    lines += [SEP, "[XSS SINKS BY FILE — ONE LINE PER FILE]", SEP]
    if by_file:
        found_any = False
        for rel, findings in sorted(by_file.items()):
            sinks = findings.get("xss_sinks", [])
            if not sinks:
                continue
            found_any = True
            sink_details = ", ".join(
                f"L{s['line']} [{_one_line(s['sink'])}] {_one_line(s['snippet'])}"
                for s in sinks
            )
            lines.append(
                f"XSS_SINK | FILE: {_one_line(rel)} | HITS: {len(sinks)} | DETAILS: {sink_details}"
            )
        if not found_any:
            lines.append("  No XSS sinks detected.")
        lines.append("")
    else:
        lines.append("  No XSS sinks detected.")
        lines.append("")

    # ── Sensitive storage ─────────────────────────────────────────────────
    lines += [SEP, "[SENSITIVE DATA IN localStorage / sessionStorage]", SEP]
    if storage:
        lines.append("  Storing credentials/tokens in Web Storage is accessible to any")
        lines.append("  same-origin JS, including injected scripts (XSS amplification).")
        lines.append("")
        for entry in storage:
            op  = entry.get("op", "?")
            lines.append(
                f"  {entry['file']}  L{entry['line']}  [{op.upper()}]  {entry['snippet']}"
            )
    else:
        lines.append("  No sensitive storage writes detected.")
    lines.append("")

    # ── postMessage without origin check ─────────────────────────────────
    lines += [SEP, "[postMessage LISTENERS WITHOUT event.origin CHECK]", SEP]
    if postmsg:
        lines.append("  OWASP V8 — message handler accepts messages from ANY origin.")
        lines.append("")
        for f in postmsg:
            lines.append(f"  {f}")
    else:
        lines.append("  None found.")
    lines.append("")

    # ── Client-side routes ────────────────────────────────────────────────
    lines += [SEP, "[CLIENT-SIDE ROUTES]", SEP]
    if routes:
        lines.append(f"  {'PATH':<40} {'FILE'}")
        lines.append("  " + "─" * 80)
        for r in sorted(routes, key=lambda x: x["path"]):
            lines.append(f"  {r['path']:<40} {r['file']}:{r['line']}")
    else:
        lines.append("  No React Router / Vue Router route definitions found.")
    lines.append("")

    return "\n".join(lines)
