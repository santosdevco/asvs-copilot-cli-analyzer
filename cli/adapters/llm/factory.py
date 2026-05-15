"""LLM provider factory."""
from __future__ import annotations

import os
from cli.adapters.llm.base import LLMProvider

_provider_instance: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    """Return singleton LLM provider based on LLM_PROVIDER env."""
    global _provider_instance

    if _provider_instance is not None:
        return _provider_instance

    provider_name = os.getenv("LLM_PROVIDER", "copilot").lower()

    if provider_name == "claude":
        from cli.adapters.llm.claude import ClaudeProvider
        _provider_instance = ClaudeProvider()
    else:
        from cli.adapters.llm.copilot import CopilotProvider
        _provider_instance = CopilotProvider()

    return _provider_instance


def get_current_model() -> str:
    """Return current model name."""
    return get_llm_provider().get_model_name()


def set_active_tools(tools: list[str] | None) -> None:
    """Set active tools for the current provider (Claude only)."""
    provider = get_llm_provider()
    if hasattr(provider, "set_active_tools"):
        provider.set_active_tools(tools)


def reset_provider() -> None:
    """Reset the provider instance (for testing or reconfiguration)."""
    global _provider_instance
    _provider_instance = None
