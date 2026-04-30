"""
analyzers/frontend.py — Frontend-specific security analysis (XSS, DOM leaks, storage).

Only runs for frontend/SPA projects.  Framework detection is performed from the
dependency list so that React-, Vue-, and Angular-specific sinks are applied only
when the relevant framework is actually present — avoiding cross-framework noise.

OWASP coverage
  V1  (Encoding/Sanitization) — XSS sinks, dangerouslySetInnerHTML, v-html
  V5  (File handling)         — blob URL injection
  V8  (Authorization)         — postMessage without origin check
  V14 (Data Protection)       — credentials/tokens in localStorage
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from ..core.fs import detect_language, read_text


# ─────────────────────────────────────────────────────────────────────────────
# Universal DOM sinks  (apply to every JS/TS frontend file)
# ─────────────────────────────────────────────────────────────────────────────

_UNIVERSAL_SINKS: list[tuple[str, re.Pattern]] = [
    # Direct HTML injection into the live DOM
    ("innerHTML",          re.compile(r"\.innerHTML\s*=(?!=)", re.I)),
    ("outerHTML",          re.compile(r"\.outerHTML\s*=(?!=)", re.I)),
    ("insertAdjacentHTML", re.compile(r"\.insertAdjacentHTML\s*\(", re.I)),
    ("document.write",     re.compile(r"\bdocument\.write\s*\(", re.I)),
    # Dynamic code execution
    ("eval",               re.compile(r"\beval\s*\(")),
    ("new Function",       re.compile(r"\bnew\s+Function\s*\(")),
    ("setTimeout string",  re.compile(r"\bsetTimeout\s*\(\s*['\"`]")),
    ("setInterval string", re.compile(r"\bsetInterval\s*\(\s*['\"`]")),
    # Open redirect — assigning user-controlled value directly to location
    ("open redirect",      re.compile(r"\bwindow\.location(?:\.href)?\s*=(?!=)")),
    # Blob / object URL injection (can load attacker-controlled content)
    ("createObjectURL",    re.compile(r"\bURL\.createObjectURL\s*\(")),
]

# ─────────────────────────────────────────────────────────────────────────────
# Framework-specific sinks
# Keyed by the lowercase framework name as returned by detect_frameworks().
# ─────────────────────────────────────────────────────────────────────────────

_FRAMEWORK_SINKS: dict[str, list[tuple[str, re.Pattern]]] = {
    # React — the only safe way to set raw HTML is through the prop below;
    # any direct innerHTML bypass is a critical finding.
    "react": [
        ("dangerouslySetInnerHTML",
         re.compile(r"\bdangerouslySetInnerHTML\s*=\s*\{\s*\{\s*__html\s*:", re.I)),
        # useRef / createRef assigned raw HTML via .current.innerHTML
        ("ref.current.innerHTML",
         re.compile(r"\b\w+Ref\.current\.innerHTML\s*=(?!=)", re.I)),
    ],

    # Vue — v-html renders raw HTML without sanitization
    "vue": [
        ("v-html",          re.compile(r"\bv-html\s*=", re.I)),
        ("$el.innerHTML",   re.compile(r"\$el\.innerHTML\s*=(?!=)", re.I)),
        ("$refs innerHTML", re.compile(r"\$refs\.\w+\.innerHTML\s*=(?!=)", re.I)),
    ],

    # Angular — DomSanitizer bypass methods are explicit trust escalations
    "angular": [
        ("[innerHTML]",
         re.compile(r"\[innerHTML\]\s*=", re.I)),
        ("bypassSecurityTrust",
         re.compile(r"\bbypassSecurityTrust(?:Html|Script|Url|ResourceUrl|Style)\s*\(", re.I)),
        ("nativeElement.innerHTML",
         re.compile(r"\bnativeElement\.innerHTML\s*=(?!=)", re.I)),
        ("Renderer2.setProperty innerHTML",
         re.compile(r"renderer(?:2)?\.setProperty\s*\([^,]+,\s*['\"]innerHTML['\"]", re.I)),
    ],

    # Svelte — {@html ...} template tag renders raw HTML
    "svelte": [
        ("{@html}",  re.compile(r"\{@html\b")),
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# Credential / token storage in Web Storage — OWASP V14
# localStorage/sessionStorage are accessible to any JS on the page (XSS risk).
# ─────────────────────────────────────────────────────────────────────────────

_STORAGE_SENSITIVE_RE = re.compile(
    r"(?:localStorage|sessionStorage)\.setItem\s*\(\s*['\"`][^'\"`]*"
    r"(?:token|password|passwd|secret|key|auth|credential|jwt|session|bearer)[^'\"`]*['\"`]",
    re.I,
)

# Also flag getItem reads of likely-sensitive keys (data already stored there)
_STORAGE_SENSITIVE_READ_RE = re.compile(
    r"(?:localStorage|sessionStorage)\.getItem\s*\(\s*['\"`][^'\"`]*"
    r"(?:token|password|passwd|secret|key|auth|credential|jwt|session|bearer)[^'\"`]*['\"`]",
    re.I,
)

# ─────────────────────────────────────────────────────────────────────────────
# postMessage without origin validation — OWASP V8
# Receiving messages without checking event.origin allows cross-origin attacks.
# ─────────────────────────────────────────────────────────────────────────────

_POSTMESSAGE_LISTENER_RE = re.compile(
    r"addEventListener\s*\(\s*['\"]message['\"]", re.I
)
_ORIGIN_CHECK_RE = re.compile(r"\bevent\.origin\b|\be\.origin\b", re.I)

# ─────────────────────────────────────────────────────────────────────────────
# CSP meta tag presence check (HTML files) — OWASP V1
# ─────────────────────────────────────────────────────────────────────────────

_CSP_META_RE = re.compile(
    r'<meta[^>]+http-equiv\s*=\s*["\']Content-Security-Policy["\']', re.I
)

# ─────────────────────────────────────────────────────────────────────────────
# React Router / client-side view routes — for the auditor map
# ─────────────────────────────────────────────────────────────────────────────

_REACT_ROUTE_RE = re.compile(
    r'<Route\b[^>]*\bpath\s*=\s*[{\'"](?P<path>/?[^\'"}{]+)[}\'""]',
    re.I,
)
_VUE_ROUTE_RE = re.compile(
    r"path\s*:\s*['\"](?P<path>/[^'\"]+)['\"]", re.I
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _detect_active_frameworks(frameworks: list[str]) -> set[str]:
    """Return lowercase framework keys present in the project dependency list."""
    active: set[str] = set()
    fw_lower = {f.lower() for f in frameworks}
    for key in _FRAMEWORK_SINKS:
        if any(key in fw for fw in fw_lower):
            active.add(key)
    return active


def _line_no(text: str, pos: int) -> int:
    return text[:pos].count("\n") + 1


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def analyze_frontend(
    files: list[Path],
    root: Path,
    frameworks: list[str],
    is_frontend: bool = True,
) -> dict:
    """
    Scan frontend source files for XSS sinks, unsafe storage, postMessage gaps,
    and client-side route definitions.

    Parameters
    ----------
    files       : all project files (as collected by collect_files)
    root        : project root Path
    frameworks  : detected framework list from detect_frameworks()
    is_frontend : set to False to skip and return an empty placeholder
    """
    if not is_frontend:
        return {"available": False, "_note": "skipped: not a frontend project"}

    active_fw = _detect_active_frameworks(frameworks)

    # Build the effective sink list for this project
    effective_sinks = list(_UNIVERSAL_SINKS)
    for fw in active_fw:
        effective_sinks.extend(_FRAMEWORK_SINKS.get(fw, []))

    findings_by_file: dict[str, dict] = {}
    csp_found = False
    routes: list[dict] = []
    storage_writes: list[dict] = []
    postmsg_without_origin: list[str] = []

    for f in files:
        lang = detect_language(f)
        rel = str(f.relative_to(root))

        # CSP check — scan HTML / HTM files
        if f.suffix.lower() in {".html", ".htm"}:
            text = read_text(f) or ""
            if _CSP_META_RE.search(text):
                csp_found = True
            continue

        if lang not in {"JavaScript", "TypeScript"}:
            continue

        text = read_text(f)
        if not text:
            continue

        file_findings: dict = {}

        # ── XSS sinks ────────────────────────────────────────────────────
        sinks_hit: list[dict] = []
        for label, pat in effective_sinks:
            for m in pat.finditer(text):
                snippet = text[m.start(): m.start() + 80].replace("\n", " ").strip()
                sinks_hit.append({
                    "sink":    label,
                    "line":    _line_no(text, m.start()),
                    "snippet": snippet,
                })
        if sinks_hit:
            file_findings["xss_sinks"] = sinks_hit

        # ── Sensitive storage writes ──────────────────────────────────────
        for m in _STORAGE_SENSITIVE_RE.finditer(text):
            snippet = m.group(0)[:80].replace("\n", " ").strip()
            storage_writes.append({
                "file":    rel,
                "line":    _line_no(text, m.start()),
                "snippet": snippet,
                "op":      "write",
            })
        for m in _STORAGE_SENSITIVE_READ_RE.finditer(text):
            snippet = m.group(0)[:80].replace("\n", " ").strip()
            storage_writes.append({
                "file":    rel,
                "line":    _line_no(text, m.start()),
                "snippet": snippet,
                "op":      "read",
            })

        # ── postMessage without origin check ─────────────────────────────
        if _POSTMESSAGE_LISTENER_RE.search(text):
            if not _ORIGIN_CHECK_RE.search(text):
                postmsg_without_origin.append(rel)

        # ── Client-side routes ────────────────────────────────────────────
        for m in _REACT_ROUTE_RE.finditer(text):
            routes.append({"path": m.group("path"), "file": rel,
                           "line": _line_no(text, m.start()), "framework": "React"})
        if "vue" in active_fw:
            for m in _VUE_ROUTE_RE.finditer(text):
                routes.append({"path": m.group("path"), "file": rel,
                               "line": _line_no(text, m.start()), "framework": "Vue"})

        if file_findings:
            findings_by_file[rel] = file_findings

    # ── Severity roll-up ─────────────────────────────────────────────────────
    total_sinks = sum(
        len(v.get("xss_sinks", []))
        for v in findings_by_file.values()
    )
    critical_files = [
        rel for rel, v in findings_by_file.items()
        if any(
            s["sink"] in {
                "dangerouslySetInnerHTML", "bypassSecurityTrust",
                "v-html", "[innerHTML]", "innerHTML", "eval",
            }
            for s in v.get("xss_sinks", [])
        )
    ]

    return {
        "available":               True,
        "active_frameworks":       sorted(active_fw),
        "total_xss_sink_hits":     total_sinks,
        "critical_files":          sorted(critical_files),
        "findings_by_file":        findings_by_file,
        "storage_sensitive":       storage_writes,
        "postmessage_no_origin":   postmsg_without_origin,
        "csp_meta_found":          csp_found,
        "client_routes":           routes,
        "total_client_routes":     len(routes),
    }
