"""
formatters/__init__.py — Exports FORMATTERS and SECTION_TXT_FORMATTERS dicts.
"""
from __future__ import annotations

from typing import Callable

from .json_fmt import format_json, format_json_compact
from .md_fmt import format_md
from .txt_fmt import format_txt
from .sections.database import format_database_txt
from .sections.code_signals import format_code_signals_txt
from .sections.imports import format_imports_txt
from .sections.middlewares import format_middlewares_txt
from .sections.identity import format_identity_txt
from .sections.structure import format_structure_txt
from .sections.endpoints import format_endpoints_txt
from .sections.env_vars import format_env_vars_txt
from .sections.security import format_security_txt
from .sections.git import format_git_txt
from .sections.frontend import format_frontend_txt

FORMATTERS: dict[str, Callable[[dict], str]] = {
    "json":    format_json,
    "compact": format_json_compact,
    "md":      format_md,
    "txt":     format_txt,
}

SECTION_TXT_FORMATTERS: dict[str, Callable[[dict, dict], str]] = {
    "identity":     format_identity_txt,
    "structure":    format_structure_txt,
    "endpoints":    format_endpoints_txt,
    "env_vars":     format_env_vars_txt,
    "database":     format_database_txt,
    "middlewares":  format_middlewares_txt,
    "imports":      format_imports_txt,
    "code_signals": format_code_signals_txt,
    "security":     format_security_txt,
    "git":          format_git_txt,
    "frontend":     format_frontend_txt,
}
