"""
rules/__init__.py — Exports the singleton RULE_ENGINE with all registered languages.
"""
from .base import RuleEngine
from .javascript import RULES as JS_RULES
from .python_rules import RULES as PY_RULES
from .java import RULES as JAVA_RULES
from .go import RULES as GO_RULES

RULE_ENGINE = RuleEngine()
RULE_ENGINE.register(JS_RULES)
RULE_ENGINE.register(PY_RULES)
RULE_ENGINE.register(JAVA_RULES)
RULE_ENGINE.register(GO_RULES)

# Language aliases (EXT_TO_LANG values → canonical rule language)
RULE_ENGINE.register_alias("TypeScript", "JavaScript")
RULE_ENGINE.register_alias("Kotlin", "Java")

__all__ = ["RULE_ENGINE", "RuleEngine"]
