"""
analyzers/endpoints.py — HTTP route declaration extraction (JS/TS/Python).
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from ..core.fs import detect_language, read_text


# ── Regexes ───────────────────────────────────────────────────────────────────

_ROUTE_LINE_RE = re.compile(
    r"""
    (?:router|app|Route|server|v\w+)\s*
    \.\s*
    (get|post|put|patch|delete|head|options|use)
    \s*\(\s*
    ['"`]([^'"`\n]+)['"`]
    ((?:\s*,\s*[\w.$\[\]()\s'"`={}:]+)*)
    \s*\)
    """,
    re.VERBOSE | re.I,
)

_PY_ROUTE_RE = re.compile(
    r"""
    @\s*(?:app|router|blueprint|bp)\s*\.\s*
    (get|post|put|patch|delete|head|route)
    \s*\(\s*['"`]([^'"`\n]+)['"`]
    """,
    re.VERBOSE | re.I,
)

_ROUTE_PARAM_RE = re.compile(r":(\w+)")

# React Router v5/v6: <Route path="/foo" .../> or <Route path='/foo'>
_REACT_ROUTE_RE = re.compile(
    r'<Route\b[^>]*\bpath\s*=\s*[{\'"](/?[^\'"}{]+)[}\'"]',
    re.I,
)

_AUTH_MW_TOKENS = frozenset({
    "validjwt", "validpermission", "validagent", "authmiddleware",
    "checkrole", "isadmin", "authenticate", "authorize", "requireauth",
    "ensureauth", "jwtauth", "bearerauth",
})


# Matches any quoted string (single, double, or backtick) — used to blank them
# before splitting on commas so validator message strings don't leak as tokens.
_STRING_LITERAL_RE = re.compile(r'([`\'"]).+?\1', re.S)

# A valid JS identifier (possibly with dots/brackets for member access).
_VALID_IDENT_RE = re.compile(r'^[A-Za-z_$][\w$.]*$')


def _parse_handlers(raw_args: str) -> tuple[list[str], str]:
    # Blank out string literals so comma-split is not fooled by e.g.
    # check("username", "The field is required").
    sanitized = _STRING_LITERAL_RE.sub('""', raw_args)
    parts = [
        p.strip()
        for p in re.split(r'\s*,\s*', sanitized.strip().strip(','))
        # Keep only bare identifiers; discard brackets, quoted remnants, etc.
        if _VALID_IDENT_RE.match(p.strip())
    ]
    if not parts:
        return [], ''
    return parts[:-1], parts[-1]


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_endpoints(files: list[Path], root: Path) -> dict:
    endpoints: list[dict] = []
    routes_per_file: dict[str, int] = {}

    for f in files:
        lang = detect_language(f)
        if lang not in {"JavaScript", "TypeScript", "Python"}:
            continue
        text = read_text(f)
        if not text:
            continue

        rel = str(f.relative_to(root))
        count = 0

        if lang in {"JavaScript", "TypeScript"}:
            for m in _ROUTE_LINE_RE.finditer(text):
                method = m.group(1).upper()
                path   = m.group(2)
                raw    = m.group(3) or ""
                middlewares, handler = _parse_handlers(raw)
                endpoints.append({
                    "method":      method,
                    "path":        path,
                    "file":        rel,
                    "line":        text[: m.start()].count("\n") + 1,
                    "middlewares": middlewares,
                    "handler":     handler,
                })
                count += 1
        elif lang == "Python":
            for m in _PY_ROUTE_RE.finditer(text):
                endpoints.append({
                    "method":      m.group(1).upper(),
                    "path":        m.group(2),
                    "file":        rel,
                    "line":        text[: m.start()].count("\n") + 1,
                    "middlewares": [],
                    "handler":     "",
                })
                count += 1

        # React Router: collect browser-side view paths (no HTTP method)
        if lang in {"JavaScript", "TypeScript"}:
            for m in _REACT_ROUTE_RE.finditer(text):
                endpoints.append({
                    "method":      "VIEW",
                    "path":        m.group(1),
                    "file":        rel,
                    "line":        text[: m.start()].count("\n") + 1,
                    "middlewares": [],
                    "handler":     "",
                })
                count += 1

        if count:
            routes_per_file[rel] = count

    # Domain map — group by first path segment
    domains: dict[str, set] = defaultdict(set)
    for ep in endpoints:
        parts = [p for p in ep["path"].split("/") if p and not p.startswith(":")]
        prefix = parts[0] if parts else "/"
        domains[prefix].add(ep["method"])

    # Annotate route parameters
    for ep in endpoints:
        params = _ROUTE_PARAM_RE.findall(ep["path"])
        if params:
            ep["route_params"] = params

    # Unprotected routes
    unprotected: list[dict] = []
    for ep in endpoints:
        mw_clean = {re.sub(r"[^a-z]", "", t.lower()) for t in ep.get("middlewares", [])}
        if not (mw_clean & _AUTH_MW_TOKENS):
            entry: dict = {
                "method": ep["method"], "path": ep["path"],
                "file": ep["file"], "line": ep["line"],
            }
            if ep.get("route_params"):
                entry["route_params"] = ep["route_params"]
            unprotected.append(entry)

    return {
        "total":              len(endpoints),
        "routes_per_file":    routes_per_file,
        "domain_map":         {k: sorted(v) for k, v in sorted(domains.items())},
        "endpoints":          endpoints,
        "unprotected_routes": unprotected,
        "total_unprotected":  len(unprotected),
    }
