"""Claude Agent SDK provider implementation."""
from __future__ import annotations

import os
import json
import sys
from pathlib import Path
from rich.console import Console
from cli.adapters.llm.base import LLMProvider, LLMResponse, LLMUsage

console = Console(stderr=True)

_ALLOWED_TOOLS = ["Read", "Write", "Edit", "Bash", "Grep", "Glob", "LS", "WebSearch", "WebFetch"]


class ClaudeProvider(LLMProvider):
    """Claude Agent SDK provider with full tool access."""

    def __init__(self):
        self.settings = self._load_settings()
        self.model = self._resolve_model()

    def execute(self, prompt: str, streaming: bool = False, interactive: bool = False) -> LLMResponse:
        """Execute via Claude Agent SDK using query() function."""
        import anyio
        from claude_agent_sdk import (
            query,
            ClaudeAgentOptions,
            AssistantMessage,
            ResultMessage,
            TextBlock,
            ToolUseBlock,
        )

        options = ClaudeAgentOptions(
            model=self.model,
            tools=_ALLOWED_TOOLS,
            max_turns=20,
            permission_mode="acceptEdits",
        )

        full_response = []
        usage_data = LLMUsage()

        async def _run_query():
            try:
                async for message in query(prompt=prompt, options=options):
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                full_response.append(block.text)
                                if streaming:
                                    sys.stdout.write(block.text)
                                    sys.stdout.flush()
                            elif isinstance(block, ToolUseBlock):
                                if streaming:
                                    tool_name = getattr(block, "name", "unknown")
                                    tool_input = getattr(block, "input", {})

                                    # Extract key parameters based on tool type
                                    params = []
                                    if tool_name == "Read":
                                        if "file_path" in tool_input:
                                            params.append(f"file: {tool_input['file_path']}")
                                    elif tool_name == "Write":
                                        if "file_path" in tool_input:
                                            params.append(f"file: {tool_input['file_path']}")
                                    elif tool_name == "Edit":
                                        if "file_path" in tool_input:
                                            params.append(f"file: {tool_input['file_path']}")
                                    elif tool_name == "Bash":
                                        if "command" in tool_input:
                                            cmd = tool_input['command']
                                            # Truncate long commands
                                            if len(cmd) > 60:
                                                cmd = cmd[:60] + "..."
                                            params.append(f"cmd: {cmd}")
                                    elif tool_name == "Grep":
                                        if "pattern" in tool_input:
                                            params.append(f"pattern: {tool_input['pattern']}")
                                        if "path" in tool_input:
                                            params.append(f"path: {tool_input['path']}")
                                    elif tool_name == "Glob":
                                        if "pattern" in tool_input:
                                            params.append(f"pattern: {tool_input['pattern']}")

                                    # Format output
                                    if params:
                                        params_str = " | ".join(params)
                                        console.print(f"\n🔧 [bold cyan]{tool_name}[/bold cyan] [dim]({params_str})[/dim]", end="")
                                    else:
                                        console.print(f"\n🔧 [bold cyan]{tool_name}[/bold cyan]", end="")

                    elif isinstance(message, ResultMessage):
                        usage = getattr(message, "usage", None)
                        if usage:
                            usage_data.input_tokens = float(getattr(usage, "input_tokens", 0) or 0)
                            usage_data.output_tokens = float(getattr(usage, "output_tokens", 0) or 0)
                            usage_data.cache_read_tokens = float(getattr(usage, "cache_read_tokens", 0) or 0)
                            usage_data.cache_write_tokens = float(getattr(usage, "cache_write_tokens", 0) or 0)
                            usage_data.total_cost_usd = float(getattr(message, "total_cost_usd", 0) or 0)
                            usage_data.num_turns = int(getattr(message, "num_turns", 0) or 0)
            except Exception as e:
                # Log error but continue - Claude may have written files before failing
                error_msg = str(e)
                console.print(f"\n[yellow]⚠ Warning: {error_msg}[/yellow]")
                # Add error context to response
                full_response.append(f"\n\n<!-- Error during execution: {error_msg} -->")

        anyio.run(_run_query)

        if streaming:
            console.print()

        return LLMResponse(
            text="".join(full_response),
            usage=usage_data,
            metadata={"provider": "claude", "model": self.model},
        )

    def get_model_name(self) -> str:
        return self.model

    def get_provider_name(self) -> str:
        return "claude"

    def _load_settings(self) -> dict:
        """Load ~/.claude/settings.json."""
        path = Path.home() / ".claude" / "settings.json"
        if not path.exists():
            return {}
        try:
            with path.open() as f:
                settings = json.load(f)
            for key, value in (settings.get("env") or {}).items():
                os.environ.setdefault(key, str(value))
            return settings
        except Exception:
            return {}

    def _resolve_model(self) -> str:
        """Resolve model from env or settings."""
        explicit = os.getenv("LLM_MODEL", "").strip()
        if explicit:
            if explicit.lower() == "sonnet":
                return (self.settings.get("env") or {}).get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4.6")
            if explicit.lower() == "opus":
                return (self.settings.get("env") or {}).get("ANTHROPIC_DEFAULT_OPUS_MODEL", "claude-opus-4.7")
            return explicit

        model_alias = self.settings.get("model", "sonnet").lower()
        if model_alias == "opus":
            return (self.settings.get("env") or {}).get("ANTHROPIC_DEFAULT_OPUS_MODEL", "claude-opus-4.7")
        return (self.settings.get("env") or {}).get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4.6")
