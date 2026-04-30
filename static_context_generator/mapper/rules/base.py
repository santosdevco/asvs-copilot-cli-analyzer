"""
rules/base.py — Rule Engine core.

A LanguageRules object holds all regex rule sets for one language.
RuleEngine dispatches analysis to the correct LanguageRules instance
based on the detected file language.

Adding a new language:
  1. Create  mapper/rules/<lang>.py  with a  RULES = LanguageRules(...)  export.
  2. Register it in  mapper/rules/__init__  via  REGISTRY.register().
  3. Done — no other changes needed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Domain model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LanguageRules:
    """All regex rule-sets for one language."""
    language: str

    # Category → list of (label, compiled_regex)
    sinks:       list[tuple[str, re.Pattern]] = field(default_factory=list)
    sources:     list[tuple[str, re.Pattern]] = field(default_factory=list)
    crypto:      list[tuple[str, re.Pattern]] = field(default_factory=list)
    error_leaks: list[tuple[str, re.Pattern]] = field(default_factory=list)

    # SQL injection: raw user input concatenated into a query string
    sqli_patterns: list[re.Pattern] = field(default_factory=list)

    # Parameterized / safe query patterns (positive signal — reduces noise)
    safe_query_patterns: list[re.Pattern] = field(default_factory=list)

    # Authorization guard tokens — strings (exact word match) or compiled patterns
    auth_guard_tokens: frozenset = field(default_factory=frozenset)

    # User-controlled ID field patterns (authz gap detection)
    user_id_patterns: list[re.Pattern] = field(default_factory=list)

    # JWT-specific checks (optional, JS-focused but can be extended)
    jwt_sign_re:   Optional[re.Pattern] = None
    jwt_verify_re: Optional[re.Pattern] = None

    # Input destructuring → sensitive field detection
    destructure_patterns: list[re.Pattern] = field(default_factory=list)
    simple_field_re:      Optional[re.Pattern] = None

    # Missing validation guard
    validation_guard_re: Optional[re.Pattern] = None


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

class RuleEngine:
    """
    Dispatch security analysis to the correct LanguageRules.
    Maintains a language-name → LanguageRules registry.
    Languages not in the registry receive a no-op empty result.
    """

    def __init__(self) -> None:
        self._registry: dict[str, LanguageRules] = {}

    def register(self, rules: LanguageRules) -> None:
        """Register a LanguageRules object.  May be called for aliases too."""
        self._registry[rules.language] = rules

    def register_alias(self, alias: str, language: str) -> None:
        """Make `alias` point to the same rules as `language`."""
        if language in self._registry:
            self._registry[alias] = self._registry[language]

    def supports(self, language: Optional[str]) -> bool:
        return language in self._registry

    def scan(self, text: str, language: Optional[str]) -> dict:
        """
        Run all rule sets against `text` for the given language.
        Returns a dict of findings; keys are only present when non-empty.
        """
        if not language or language not in self._registry:
            return {}
        rules = self._registry[language]
        return _apply_rules(text, rules)


# ─────────────────────────────────────────────────────────────────────────────
# Core analysis logic  (language-agnostic — operates on any LanguageRules)
# ─────────────────────────────────────────────────────────────────────────────

_TODO_RE = re.compile(
    r"(?:#|//|/\*)\s*(TODO|FIXME|HACK|XXX|BUG|NOTE)[:\s]\s*(.{0,120})",
    re.IGNORECASE,
)

_SENSITIVE_NAMES: frozenset[str] = frozenset({
    "password", "passwd", "pwd", "secret", "token", "api_key", "apikey",
    "private_key", "signing_key", "credential", "otp", "code", "pin",
    "mfa", "totp", "key", "jwt", "refresh_token", "access_token",
    "card_number", "cvv", "ssn", "account_number", "auth",
})


def _apply_rules(text: str, rules: LanguageRules) -> dict:
    result: dict = {}

    # 1. TODO / FIXME text
    todos = [
        {"type": m.group(1).upper(), "text": m.group(2).strip()}
        for m in _TODO_RE.finditer(text)
    ]
    if todos:
        result["todos"] = todos

    # 2. Dangerous sinks
    sinks = [label for label, pat in rules.sinks if pat.search(text)]
    if sinks:
        result["sinks"] = sinks

    # 3. Input sources — count occurrences
    sources = {
        label: len(pat.findall(text))
        for label, pat in rules.sources
        if pat.search(text)
    }
    if sources:
        result["sources"] = sources

    # 4. Crypto usage
    crypto = [label for label, pat in rules.crypto if pat.search(text)]
    if crypto:
        result["crypto"] = crypto

    # 5. SQL injection hints
    sqli: list[str] = []
    for pat in rules.sqli_patterns:
        for m in pat.finditer(text):
            snippet = m.group(0)[:100].replace("\n", " ").strip()
            if snippet not in sqli:
                sqli.append(snippet)
    if sqli:
        result["sqli_hints"] = sqli[:5]

    # 5b. Parameterized / safe queries (positive signal)
    pq_count = sum(len(pat.findall(text)) for pat in rules.safe_query_patterns)
    if pq_count:
        result["parameterized_queries"] = pq_count

    # 5c. Sensitive field names
    sensitive: list[str] = []
    seen: set[str] = set()
    for pat in rules.destructure_patterns:
        for m in pat.finditer(text):
            for field_name in re.split(r"[,\s]+", m.group(1)):
                f = field_name.strip().rstrip(",:")
                if f and f.lower() in _SENSITIVE_NAMES and f.lower() not in seen:
                    sensitive.append(f)
                    seen.add(f.lower())
    if rules.simple_field_re:
        for m in rules.simple_field_re.finditer(text):
            f = m.group(1)
            if f.lower() in _SENSITIVE_NAMES and f.lower() not in seen:
                sensitive.append(f)
                seen.add(f.lower())
    if sensitive:
        result["sensitive_fields"] = sensitive

    # 5d. JWT options checks
    jwt_issues: list[str] = []
    if rules.jwt_sign_re:
        for m in rules.jwt_sign_re.finditer(text):
            if "algorithm" not in m.group(0).lower():
                jwt_issues.append("jwt.sign: no algorithm specified (algorithm confusion risk)")
                break
    if rules.jwt_verify_re:
        for m in rules.jwt_verify_re.finditer(text):
            if "algorithms" not in m.group(0).lower():
                jwt_issues.append("jwt.verify: no algorithms array (algorithm confusion risk)")
                break
    if jwt_issues:
        result["jwt_issues"] = jwt_issues

    # 5e. Missing input validation guard
    has_sources = bool(sources)
    has_validation = bool(rules.validation_guard_re and rules.validation_guard_re.search(text))
    if has_sources and not has_validation:
        result["missing_input_validation"] = True

    # 6. Authorization gap
    has_id = any(pat.search(text) for pat in rules.user_id_patterns)
    if rules.auth_guard_tokens:
        string_tokens = [t for t in rules.auth_guard_tokens if isinstance(t, str)]
        pattern_tokens = [t for t in rules.auth_guard_tokens if isinstance(t, re.Pattern)]
        guard_hit = False
        if string_tokens:
            guard_hit = bool(re.search(
                r"\b(" + "|".join(re.escape(t) for t in string_tokens) + r")\b", text
            ))
        if not guard_hit and pattern_tokens:
            guard_hit = any(pat.search(text) for pat in pattern_tokens)
        has_guard = guard_hit
    else:
        has_guard = False
    if has_id and not has_guard:
        result["authz_gap"] = True

    # 7. Error leakage
    leaks: list[str] = []
    for label, pat in rules.error_leaks:
        for m in pat.finditer(text):
            snippet = m.group(0)[:80].replace("\n", " ").strip()
            if snippet not in leaks:
                leaks.append(snippet)
    if leaks:
        result["error_leaks"] = leaks[:5]

    return result
