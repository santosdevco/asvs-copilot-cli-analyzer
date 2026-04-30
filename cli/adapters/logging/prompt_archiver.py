"""Prompt archiver - saves prompts to dedicated directory with metadata."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cli.config import OUTPUTS_DIR


class PromptArchiver:
    """Archives prompts to outputs/{app}/prompts/*.xml with metadata header."""

    def __init__(self, app_name: str, command_name: str, event_logger):
        self.app_name = app_name
        self.command_name = command_name
        self.event_logger = event_logger
        self.prompts_dir = OUTPUTS_DIR / app_name / "prompts"
        self.prompts_dir.mkdir(parents=True, exist_ok=True)

    def log_prompt(self, prompt: str, label: str = "prompt", mode: str = ""):
        """Archive prompt with metadata header and log reference."""
        timestamp = datetime.now(timezone.utc)
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp_str}_{label}.xml"
        path = self.prompts_dir / filename

        header = f"""<?xml version="1.0" encoding="UTF-8"?>
<!--
  App: {self.app_name}
  Command: {self.command_name}
  Mode: {mode}
  Label: {label}
  Timestamp: {timestamp.isoformat()}
-->
"""
        path.write_text(header + prompt, encoding="utf-8")

        # Log only reference
        relative_path = path.relative_to(OUTPUTS_DIR.parent)
        self.event_logger.log_event("prompt.archived", {
            "label": label,
            "path": str(relative_path),
            "size_kb": len(prompt) // 1024,
            "timestamp": timestamp.isoformat(),
        })

        return path
