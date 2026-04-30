"""
rules/javascript.py — JavaScript/TypeScript security rules with React support.
"""
from __future__ import annotations

import re

from .base import LanguageRules


RULES = LanguageRules(    language="JavaScript",
    sinks=[
        ("eval",               re.compile(r"\beval\s*\(")),
        ("exec/spawn",         re.compile(r"\b(?:exec|execSync|spawn|spawnSync|execFile)\s*\(")),
        ("fs.write",           re.compile(r"\bfs\.(?:writeFile|appendFile|writeFileSync|appendFileSync)\s*\(")),
        ("fs.unlink/rm",       re.compile(r"\bfs\.(?:unlink|rmdir|rm|rmdirSync|unlinkSync)\s*\(")),
        ("fs.readFile",        re.compile(r"\bfs\.(?:readFile|readFileSync)\s*\(")),
        ("child_process",      re.compile(r"\brequire\(['\"]child_process['\"]\)")),
        ("vm.runInContext",    re.compile(r"\bvm\.(?:runInNewContext|runInContext|runInThisContext)\s*\(")),
        ("innerHTML",          re.compile(r"\binnerHTML\s*=")),
        ("document.write",     re.compile(r"\bdocument\.write\s*\(")),
        ("open redirect",      re.compile(r"\bres\.redirect\s*\(\s*req\.")),
        ("path traversal",     re.compile(r"(?:path\.join|path\.resolve)\s*\([^)]*req\.")),
        # React-specific dangerous patterns
        ("dangerouslySetInnerHTML", re.compile(r"\bdangerouslySetInnerHTML\s*:")),
        ("ReactDOM.render",    re.compile(r"\bReactDOM\.render\s*\(")),
        ("createRef unsafe",   re.compile(r"\bcreateRef\s*\(\)\s*\.current\s*=")),
        ("Function constructor", re.compile(r"\bnew\s+Function\s*\(")),
        ("setTimeout string",  re.compile(r"\bsetTimeout\s*\(\s*['\"]")),
        ("setInterval string", re.compile(r"\bsetInterval\s*\(\s*['\"]")),
    ],
    sources=[
        # ── Node/Express server-side sources ────────────────────────────
        ("req.body",    re.compile(r"\breq\.body\b")),
        ("req.query",   re.compile(r"\breq\.query\b")),
        ("req.params",  re.compile(r"\breq\.params\b")),
        ("req.headers", re.compile(r"\breq\.headers\b")),
        ("req.files",   re.compile(r"\breq\.files?\b")),
        # ── Frontend/React XSS sources (OWASP V5) ───────────────────────
        # Direct URL/query-string reads — classic reflected-XSS entry points.
        ("location.search",  re.compile(r"\b(?:window\.)?location\.search\b")),
        ("location.hash",    re.compile(r"\b(?:window\.)?location\.hash\b")),
        ("location.href",    re.compile(r"\b(?:window\.)?location\.href\b")),
        # Cookie/storage access — potential stored-XSS / sensitive-data exposure.
        ("document.cookie",  re.compile(r"\bdocument\.cookie\b")),
        ("localStorage",     re.compile(r"\blocalStorage\.getItem\s*\(")),
        ("sessionStorage",   re.compile(r"\bsessionStorage\.getItem\s*\(")),
        # Unescaped DOM reads fed into sinks.
        ("document.URL",     re.compile(r"\bdocument\.URL\b")),
        ("document.referrer",re.compile(r"\bdocument\.referrer\b")),
        ("URLSearchParams",  re.compile(r"new\s+URLSearchParams\s*\(")),
    ],
    auth_guard_tokens=[
        re.compile(r"\b(?:authenticate|requireAuth|isAuthenticated)\b"),
        re.compile(r"\b(?:authorize|requireRole|hasPermission)\b"),
        re.compile(r"\bmiddleware\s*\[\s*['\"]auth['\"]"),
        re.compile(r"\bcheck\w*Token\b"),
        re.compile(r"\b(?:verify|validate)(?:JWT|Token)\b"),
        # React-specific auth patterns
        re.compile(r"\buseAuth\s*\("),
        re.compile(r"\b(?:ProtectedRoute|AuthRoute)\b"),
        re.compile(r"\bisLoggedIn\b"),
    ],
)