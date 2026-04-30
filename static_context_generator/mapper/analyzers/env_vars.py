"""
analyzers/env_vars.py — Environment variable reference extraction and classification.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from ..core.fs import detect_language, read_text


# ── Regexes per language ──────────────────────────────────────────────────────

_JS_ENV_RE = re.compile(r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)")
_PY_ENV_RE = re.compile(
    r"""
    (?:os\.environ\s*\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]|
       os\.environ\.get\s*\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]|
       os\.getenv\s*\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\))
    """,
    re.VERBOSE,
)
_RB_ENV_RE = re.compile(r'ENV\s*\[\s*[\'"]([A-Za-z_][A-Za-z0-9_]*)[\'"]\s*\]')
_GO_ENV_RE = re.compile(r'os\.Getenv\s*\(\s*"([A-Za-z_][A-Za-z0-9_]*)"\s*\)')

# Classification word sets
_SECRET_WORDS  = frozenset({
    "key", "secret", "token", "signing", "private", "hmac", "jwt", "salt", "iam",
    "apikey", "api_key", "serviceinstanceid", "apikeyid", "ibmauthendpoint", 
    "mfa", "vapid", "external_channel", "push"
})
_CRED_WORDS    = frozenset({
    "password", "passwd", "pwd", "credential", "username", "user", "login", 
    "auth", "authentication", "email", "pass"
})  
_CONN_WORDS    = frozenset({
    "host", "port", "url", "uri", "endpoint", "database", "db", "schema", 
    "bucket", "region", "instance", "cos", "endpoint", "service", "version",
    "assistant", "mindx", "itsm", "agent", "area", "watson"
})


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_env_vars(files: list[Path], root: Path) -> dict:
    var_files: dict[str, set] = defaultdict(set)
    var_count: Counter = Counter()
    file_vars: dict[str, set] = defaultdict(set)

    for f in files:
        lang = detect_language(f)
        text = read_text(f)
        if not text:
            continue
        rel = str(f.relative_to(root))

        found: list[str] = []
        if lang in {"JavaScript", "TypeScript"}:
            found = _JS_ENV_RE.findall(text)
        elif lang == "Python":
            for m in _PY_ENV_RE.finditer(text):
                name = m.group(1) or m.group(2) or m.group(3)
                if name:
                    found.append(name)
        elif lang == "Ruby":
            found = _RB_ENV_RE.findall(text)
        elif lang == "Go":
            found = _GO_ENV_RE.findall(text)

        for name in found:
            var_files[name].add(rel)
            var_count[name] += 1
            file_vars[rel].add(name)

    ordered = {
        name: {
            "files":      sorted(var_files[name]),
            "references": var_count[name],
        }
        for name, _ in var_count.most_common()
    }

    classified: dict[str, list[str]] = {"SECRET": [], "CREDENTIAL": [], "CONNECTIVITY": [], "RUNTIME": []}
    for name in ordered:
        parts = set(re.split(r"[_\-]", name.lower()))
        if parts & _SECRET_WORDS:
            classified["SECRET"].append(name)
        elif parts & _CRED_WORDS:
            classified["CREDENTIAL"].append(name)
        elif parts & _CONN_WORDS:
            classified["CONNECTIVITY"].append(name)
        else:
            classified["RUNTIME"].append(name)

    return {
        "total_unique_vars":  len(ordered),
        "total_references":   sum(var_count.values()),
        "vars":               ordered,
        "files_using_env":    {f: sorted(v) for f, v in sorted(file_vars.items())},
        "classified":         {k: sorted(v) for k, v in classified.items() if v},
    }
