"""Logging factory."""
from __future__ import annotations

from cli.adapters.logging.event_logger import EventLogger
from cli.adapters.logging.prompt_archiver import PromptArchiver

_event_logger: EventLogger | None = None
_prompt_archiver: PromptArchiver | None = None


def init_logging(app_name: str, command_name: str):
    """Initialize logging for a session."""
    global _event_logger, _prompt_archiver

    _event_logger = EventLogger(app_name, command_name)
    _prompt_archiver = PromptArchiver(app_name, command_name, _event_logger)


def get_logger() -> tuple[EventLogger, PromptArchiver]:
    """Get current loggers."""
    if _event_logger is None or _prompt_archiver is None:
        raise RuntimeError("Logging not initialized. Call init_logging() first.")
    return _event_logger, _prompt_archiver
