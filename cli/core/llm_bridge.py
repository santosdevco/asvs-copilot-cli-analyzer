"""Bridge between old llm_client API and new adapter architecture.

This module provides backward-compatible functions while internally using the new adapters.
"""
from __future__ import annotations

from cli.adapters.llm import get_llm_provider
from cli.adapters.llm.factory import set_active_tools as _set_active_tools
from cli.adapters.logging import get_logger, init_logging

# Global state for backward compatibility
_session_initialized = False


def init_llm_session(app_name: str, command_name: str, active_tools: list[str] | None = None) -> None:
    """Initialize LLM session with logging and optional tool configuration."""
    global _session_initialized
    init_logging(app_name, command_name)
    if active_tools is not None:
        _set_active_tools(active_tools)
    _session_initialized = True


def finalize_llm_session():
    """Finalize LLM session."""
    global _session_initialized
    _session_initialized = False


def complete(prompt: str) -> str:
    """Execute LLM call without streaming."""
    provider = get_llm_provider()
    response = provider.execute(prompt, streaming=False)
    return response.text


def complete_interactive(prompt: str, verbose: bool = False, interactive: bool = False, streaming: bool = False, context: str = "") -> tuple[dict, str]:
    """Execute LLM call with interactive/streaming support."""
    provider = get_llm_provider()

    if _session_initialized:
        try:
            event_logger, prompt_archiver = get_logger()
            prompt_archiver.log_prompt(prompt, label=context or "audit", mode="interactive" if interactive else "batch")
        except Exception:
            pass  # Continue even if logging fails

    response = provider.execute(prompt, streaming=streaming, interactive=interactive)

    usage_summary = {
        "provider": provider.get_provider_name(),
        "model": provider.get_model_name(),
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_read_tokens": response.usage.cache_read_tokens,
        "cache_write_tokens": response.usage.cache_write_tokens,
        "total_tokens": response.usage.total_tokens,
        "total_cost_usd": response.usage.total_cost_usd,
        "num_turns": response.usage.num_turns,
    }

    return usage_summary, response.text


def get_last_usage_summary() -> dict:
    """Return last usage summary (for backward compat)."""
    return {}


def get_provider_and_model() -> tuple[str, str]:
    """Return current provider and model."""
    provider = get_llm_provider()
    return provider.get_provider_name(), provider.get_model_name()


def configure_active_tools(tools: list[str] | None) -> None:
    """Configure active tools for the LLM provider (Claude only)."""
    _set_active_tools(tools)
