"""Claude Agent SDK provider implementation."""
from __future__ import annotations

import os
import json
import sys
from pathlib import Path
from rich.console import Console
from cli.adapters.llm.base import LLMProvider, LLMResponse, LLMUsage

console = Console(stderr=True)

_DEFAULT_TOOLS = ["Read", "Write", "Edit", "Bash", "Grep", "Glob", "LS", "WebSearch", "WebFetch"]


class ClaudeProvider(LLMProvider):
    """Claude Agent SDK provider with full tool access."""

    def __init__(self):
        self.settings = self._load_settings()
        self.model = self._resolve_model()
        self.active_tools = _DEFAULT_TOOLS

    def set_active_tools(self, tools: list[str] | None) -> None:
        """Set the active tools for this provider instance."""
        if tools is None:
            self.active_tools = []
        else:
            self.active_tools = tools

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
            tools=self.active_tools,
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
                            # usage is a dict, not an object
                            if isinstance(usage, dict):
                                usage_data.input_tokens = float(usage.get("input_tokens", 0) or 0)
                                usage_data.output_tokens = float(usage.get("output_tokens", 0) or 0)
                                usage_data.cache_read_tokens = float(usage.get("cache_read_input_tokens", 0) or 0)
                                usage_data.cache_write_tokens = float(usage.get("cache_creation_input_tokens", 0) or 0)
                            else:
                                # Fallback for object-style usage
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

    def get_account_info(self) -> dict:
        """Run the claude CLI to collect version and auth status."""
        import subprocess
        import shutil

        claude_bin = shutil.which("claude") or "claude"
        info: dict = {"provider": "claude", "model": self.model}

        # Version
        try:
            out = subprocess.run([claude_bin, "--version"], capture_output=True, text=True, timeout=5)
            info["version"] = out.stdout.strip() or out.stderr.strip()
        except Exception as e:
            info["version"] = f"error — {e}"

        # Auth probe: ask claude to report its own session context
        _session_prompt = (
            'Output ONLY a JSON object (no markdown) with these keys: '
            '"email" (your authenticated user email or null), '
            '"login_method" (e.g. "Claude Pro account", "API key", "Amazon Bedrock"), '
            '"organization" (org name or null). '
            'Example: {"email":"user@example.com","login_method":"Claude Pro account","organization":"Acme"}'
        )
        try:
            out = subprocess.run(
                [claude_bin, "-p", _session_prompt, "--output-format", "json"],
                capture_output=True, text=True, timeout=30,
            )
            raw = out.stdout.strip()
            data = {}
            if raw:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    pass

            if data and not data.get("is_error"):
                info["auth"] = "ok"
                # parse inner JSON from result field
                result_str = data.get("result", "")
                try:
                    session_data = json.loads(result_str) if isinstance(result_str, str) else {}
                    if session_data.get("email"):
                        info["email"] = session_data["email"]
                    if session_data.get("login_method"):
                        info["login_method"] = session_data["login_method"]
                    if session_data.get("organization"):
                        info["organization"] = session_data["organization"]
                    # infer backend from login_method
                    lm = (session_data.get("login_method") or "").lower()
                    if "bedrock" in lm:
                        info["backend"] = "Amazon Bedrock"
                    elif "vertex" in lm:
                        info["backend"] = "Google Vertex AI"
                    elif "api key" in lm:
                        info["backend"] = "Anthropic API"
                    elif "pro" in lm or "account" in lm:
                        info["backend"] = "Claude Pro (OAuth)"
                except (json.JSONDecodeError, AttributeError):
                    pass
                cost = data.get("cost_usd") or data.get("total_cost_usd")
                if cost is not None:
                    info["probe_cost_usd"] = f"${float(cost):.6f}"
                if data.get("model"):
                    info["resolved_model"] = data["model"]
                if data.get("session_id"):
                    info["session_id"] = data["session_id"]
            elif data and data.get("is_error"):
                msg = data.get("result") or data.get("message") or f"HTTP {data.get('api_error_status','?')}"
                info["auth"] = f"error — {str(msg)[:120]}"
            else:
                info["auth"] = f"error (exit {out.returncode})"
                info["detail"] = (out.stderr or raw or "").strip()[:120]
        except Exception as e:
            info["auth"] = f"error — {e}"

        settings_env = os.environ.get("CLAUDE_SETTINGS_PATH")
        info["settings_path"] = settings_env if settings_env else str(Path.home() / ".claude" / "settings.json")
        return info

    def _load_settings(self) -> dict:
        """Load ~/.claude/settings.json."""
        settings_env = os.environ.get("CLAUDE_SETTINGS_PATH")
        path = Path(settings_env) if settings_env else Path.home() / ".claude" / "settings.json"
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
