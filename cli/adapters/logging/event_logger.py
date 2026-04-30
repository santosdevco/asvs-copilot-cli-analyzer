"""Event logging adapter - writes to log_app.log."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cli.config import OUTPUTS_DIR


class EventLogger:
    """Logs structured events to log_app.log (excludes prompts)."""

    def __init__(self, app_name: str, command_name: str):
        self.app_name = app_name
        self.command_name = command_name
        self.log_file = OUTPUTS_DIR / app_name / "log_app.log"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._write_session_header()

    def _write_session_header(self):
        """Write session start marker."""
        header = {
            "timestamp": self._now_iso(),
            "event": "session.start",
            "app_name": self.app_name,
            "command": self.command_name,
        }
        self._append("\n" + "=" * 100 + "\n")
        self._append(json.dumps(header, ensure_ascii=False, indent=2) + "\n")

    def log_event(self, event: str, data: Any = None):
        """Log structured event."""
        payload = {
            "timestamp": self._now_iso(),
            "event": event,
            "data": data,
        }
        self._append(json.dumps(payload, ensure_ascii=False) + "\n")

    def _append(self, text: str):
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(text)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
