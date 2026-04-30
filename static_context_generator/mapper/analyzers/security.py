"""
analyzers/security.py — Hardcoded-secret and exposed .env file scanner.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..core.config import SECURITY_PATTERNS
from ..core.fs import detect_language, read_text


def scan_security(files: list[Path], root: Path) -> dict:
    findings: list[dict] = []
    exposed_env: list[str] = []
    SKIP_COMMENTS = re.compile(r"^\s*(?:#|//|\*|--|<!--|;)")

    for f in files:
        name = f.name
        # Real .env files (not templates / examples)
        if name == ".env" or re.match(r"^\.env\.[a-z]+$", name, re.I):
            if not any(w in name.lower() for w in ("example", "sample", "template", "test")):
                exposed_env.append(str(f.relative_to(root)))

        lang = detect_language(f)
        if lang in {"Markdown"}:
            continue

        text = read_text(f, max_bytes=500_000)
        if not text:
            continue

        for line_no, line in enumerate(text.splitlines(), 1):
            if SKIP_COMMENTS.match(line):
                continue
            for pattern, ptype in SECURITY_PATTERNS:
                if pattern.search(line):
                    masked = re.sub(r'["\'][^"\']{4,}["\']', '"[REDACTED]"', line.strip())
                    findings.append({
                        "file":    str(f.relative_to(root)),
                        "line":    line_no,
                        "type":    ptype,
                        "snippet": masked[:150],
                    })
                    break  # one finding per line max

    return {
        "exposed_env_files": exposed_env,
        "potential_secrets": findings,
        "total_findings":    len(findings) + len(exposed_env),
    }
