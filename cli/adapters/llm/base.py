"""LLM provider interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMUsage:
    """Normalized usage metrics across providers."""
    input_tokens: float = 0.0
    output_tokens: float = 0.0
    cache_read_tokens: float = 0.0
    cache_write_tokens: float = 0.0
    reasoning_tokens: float = 0.0
    total_cost_usd: float = 0.0
    num_turns: int = 0

    @property
    def total_tokens(self) -> float:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMResponse:
    """Unified response format."""
    text: str
    usage: LLMUsage
    metadata: dict[str, Any]


class LLMProvider(ABC):
    """Abstract LLM provider interface."""

    @abstractmethod
    def execute(self, prompt: str, streaming: bool = False, interactive: bool = False) -> LLMResponse:
        """Execute LLM call and return normalized response."""

    @abstractmethod
    def get_model_name(self) -> str:
        """Return current model identifier."""

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return provider name (copilot, claude, etc)."""

    @abstractmethod
    def get_account_info(self) -> dict:
        """Return account/auth info for the current provider."""
