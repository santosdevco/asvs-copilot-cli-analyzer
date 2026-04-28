"""
app_logger.py
─────────────
Per-application execution log writer.
Writes audit traces to: outputs/<app_name>/log_app.log
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from cli.config import OUTPUTS_DIR

_LOG_FILE: Path | None = None
_CURRENT_APP: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(text: str) -> None:
    if _LOG_FILE is None:
        return
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(text)


def init_app_logger(
    app_name: str,
    command_name: str,
    command_line: str,
    options: dict[str, Any] | None = None,
) -> Path:
    """Initialize per-app logger and write a command session header."""
    global _LOG_FILE, _CURRENT_APP

    _CURRENT_APP = app_name
    _LOG_FILE = OUTPUTS_DIR / app_name / "log_app.log"

    header = {
        "timestamp": _now_iso(),
        "app_name": app_name,
        "command": command_name,
        "command_line": command_line,
        "options": options or {},
    }
    _append("\n" + "=" * 100 + "\n")
    _append("SESSION START\n")
    _append(json.dumps(header, ensure_ascii=False, indent=2) + "\n")
    return _LOG_FILE


def get_log_file() -> Path | None:
    return _LOG_FILE


def log_event(event: str, data: Any = None) -> None:
    """Write a generic event block to the current app log."""
    payload = {
        "timestamp": _now_iso(),
        "event": event,
        "data": data,
    }
    _append(json.dumps(payload, ensure_ascii=False) + "\n")


def log_prompt(prompt: str, label: str = "llm_prompt") -> None:
    """Persist full prompt text to log file."""
    _append(f"\n--- {label.upper()} START [{_now_iso()}] ---\n")
    _append(prompt)
    _append(f"\n--- {label.upper()} END ---\n")


def log_output(output: str, label: str = "llm_output") -> None:
    """Persist full model output text to log file."""
    _append(f"\n--- {label.upper()} START [{_now_iso()}] ---\n")
    _append(output)
    _append(f"\n--- {label.upper()} END ---\n")
