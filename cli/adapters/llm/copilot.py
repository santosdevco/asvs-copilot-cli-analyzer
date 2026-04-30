"""Copilot provider implementation."""
from __future__ import annotations

import os
from rich.console import Console
from cli.adapters.llm.base import LLMProvider, LLMResponse, LLMUsage

console = Console(stderr=True)


class CopilotProvider(LLMProvider):
    """GitHub Copilot SDK provider."""

    def __init__(self):
        self.model = os.getenv("LLM_MODEL", "claude-sonnet-4.6")
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "8192"))
        self._session = None

    def execute(self, prompt: str, streaming: bool = False, interactive: bool = False) -> LLMResponse:
        """Execute via Copilot SDK."""
        from github_copilot_sdk import CopilotSDK, TokenLimits

        if self._session is None:
            self._session = CopilotSDK()

        limits = TokenLimits(max_prompt_tokens=200_000, max_completion_tokens=self.max_tokens)

        full_response = []
        cumulative_usage = LLMUsage()

        for message in self._session.prompt(prompt, model=self.model, token_limits=limits):
            if hasattr(message, "usage"):
                usage = message.usage
                cumulative_usage.input_tokens += float(getattr(usage, "input_tokens", 0) or 0)
                cumulative_usage.output_tokens += float(getattr(usage, "output_tokens", 0) or 0)
                cumulative_usage.cache_read_tokens += float(getattr(usage, "cache_read_tokens", 0) or 0)
                cumulative_usage.cache_write_tokens += float(getattr(usage, "cache_write_tokens", 0) or 0)

            if hasattr(message, "text") and message.text:
                full_response.append(message.text)
                if streaming:
                    console.print(message.text, end="")

        if streaming:
            console.print()

        return LLMResponse(
            text="".join(full_response),
            usage=cumulative_usage,
            metadata={"provider": "copilot", "model": self.model},
        )

    def get_model_name(self) -> str:
        return self.model

    def get_provider_name(self) -> str:
        return "copilot"
