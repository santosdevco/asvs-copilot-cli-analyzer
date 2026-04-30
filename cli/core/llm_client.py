"""
llm_client.py
─────────────
Thin abstraction over LLM providers.  Configure via environment variables:

  LLM_PROVIDER      = copilot (default) | openai | anthropic | claude
  LLM_MODEL         = claude-sonnet-4.6 (default) | gpt-4o | o4-mini | ...
  LLM_MAX_TOKENS    = 8192 (default)

  -- Copilot provider (default) -----------------------------------------------
  Uses the official `github-copilot-sdk` (pip install github-copilot-sdk).
  Auth: set GITHUB_TOKEN (or GH_TOKEN / COPILOT_GITHUB_TOKEN) env var.
  The Copilot CLI is bundled with the SDK -- no separate install needed.

  -- Claude provider (claude-agent-sdk-python) ---------------------------------
  LLM_PROVIDER=claude
  Uses `claude-agent-sdk` (pip install claude-agent-sdk).
  Auth: the bundled Claude Code CLI reads ~/.claude/ automatically.
  Override the model with LLM_MODEL (e.g. "sonnet", "opus", or a full ID).
  No extra env vars needed -- credentials are loaded from ~/.claude/settings.json.

  -- Alternative providers -----------------------------------------------------
  OPENAI_API_KEY    = sk-...    (LLM_PROVIDER=openai)
  ANTHROPIC_API_KEY = sk-ant-... (LLM_PROVIDER=anthropic)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any
from pathlib import Path

from dotenv import load_dotenv
from .app_logger import log_event, log_output, log_prompt
from .usage_tracker import (
    get_usage_tracker,
    init_usage_tracker,
    finalize_usage_tracker,
)

load_dotenv()

_PROVIDER   = os.getenv("LLM_PROVIDER", "copilot").lower()
_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8192"))

# -- ~/.claude/settings.json loader -------------------------------------------

_CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

_CLAUDE_SONNET_ENV_KEY = "ANTHROPIC_DEFAULT_SONNET_MODEL"
_CLAUDE_OPUS_ENV_KEY   = "ANTHROPIC_DEFAULT_OPUS_MODEL"
_CLAUDE_HAIKU_ENV_KEY  = "ANTHROPIC_DEFAULT_HAIKU_MODEL"

# Friendly alias → env key inside settings.json["env"]
_CLAUDE_MODEL_ALIASES: dict[str, str] = {
    "sonnet": _CLAUDE_SONNET_ENV_KEY,
    "opus":   _CLAUDE_OPUS_ENV_KEY,
    "haiku":  _CLAUDE_HAIKU_ENV_KEY,
}


def _load_claude_settings() -> dict:
    """
    Parse ~/.claude/settings.json and return its contents.
    Also injects the 'env' block into os.environ so that
    AnthropicBedrock picks up AWS_* and CLAUDE_CODE_USE_BEDROCK automatically.
    Returns {} if the file does not exist or cannot be parsed.
    """
    if not _CLAUDE_SETTINGS_PATH.exists():
        return {}
    try:
        with _CLAUDE_SETTINGS_PATH.open() as fh:
            settings: dict = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}

    # Inject every key from settings["env"] into os.environ (non-destructive:
    # existing env vars take priority so the user can still override them).
    for key, value in (settings.get("env") or {}).items():
        os.environ.setdefault(key, str(value))

    return settings


def _resolve_claude_model(settings: dict) -> str:
    """
    Resolve the Bedrock model ID to use, in priority order:
      1. LLM_MODEL env var (explicit override)
      2. LLM_MODEL alias: "sonnet" | "opus" | "haiku"  → look up in settings.env
      3. settings["model"] alias → look up in settings.env
      4. ANTHROPIC_DEFAULT_SONNET_MODEL from settings.env (safe fallback)
    """
    explicit = os.getenv("LLM_MODEL", "").strip()
    if explicit:
        # If it's a known alias, resolve it; otherwise use as-is (full model ID).
        env_key = _CLAUDE_MODEL_ALIASES.get(explicit.lower())
        if env_key:
            resolved = (settings.get("env") or {}).get(env_key) or os.getenv(env_key)
            if resolved:
                return resolved
        return explicit

    # Fall back to the alias stored in settings["model"]
    alias = (settings.get("model") or "sonnet").lower()
    env_key = _CLAUDE_MODEL_ALIASES.get(alias, _CLAUDE_SONNET_ENV_KEY)
    resolved = (settings.get("env") or {}).get(env_key) or os.getenv(env_key)
    if resolved:
        return resolved

    # Last resort: the Sonnet env var or a hardcoded stable ID
    return os.getenv(_CLAUDE_SONNET_ENV_KEY, "us.anthropic.claude-sonnet-4-5-20250929-v1:0")


# Resolve model at import time (after dotenv is loaded).
# For the 'claude' provider the model is resolved lazily inside _complete_claude_bedrock
# because _load_claude_settings() must run first.
_MODEL = os.getenv("LLM_MODEL", "gpt-4.1")  # valid: gpt-4.1, gpt-5-mini, claude-sonnet-4.6, auto …

_SYSTEM_PROMPT = "You are an expert application security auditor specialized in OWASP ASVS v5.0."

_WORKSPACE_ROOT = str(Path.cwd())
_LAST_USAGE_SUMMARY: dict[str, Any] | None = None

# -- JSON extraction helper ----------------------------------------------------

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)```", re.IGNORECASE)


def extract_json(text: str) -> str:
    """Return the first JSON block found inside *text* (strips markdown fences)."""
    match = _JSON_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    start = text.find("{")
    if start == -1:
        start = text.find("[")
    if start != -1:
        return text[start:].strip()
    return text.strip()


def parse_json(text: str) -> Any:
    """Extract and parse JSON from an LLM response string."""
    return json.loads(extract_json(text))


def _normalize_tool_args(raw_args: Any) -> dict[str, Any]:
    """Best-effort normalize SDK tool arguments to a dictionary."""
    if raw_args is None:
        return {}
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str):
        text = raw_args.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {"raw": text}

    # Pydantic/dataclass-like objects from SDK may expose useful fields.
    for attr in ("model_dump", "dict"):
        method = getattr(raw_args, attr, None)
        if callable(method):
            try:
                parsed = method()
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
    return {}


def _extract_tool_event_args(event_data: Any) -> dict[str, Any]:
    """Extract tool argument payloads from different SDK event schemas."""
    for attr in ("arguments", "input", "tool_input", "parameters", "args"):
        value = getattr(event_data, attr, None)
        parsed = _normalize_tool_args(value)
        if parsed:
            return parsed
    return {}


def _shorten_workspace_path(path_value: str) -> str:
    """Convert absolute workspace paths to relative ones for readability."""
    if not isinstance(path_value, str):
        return str(path_value)
    if path_value.startswith(_WORKSPACE_ROOT + os.sep):
        return path_value[len(_WORKSPACE_ROOT) + 1 :]
    return path_value


def _summarize_tool_args(args: dict[str, Any]) -> tuple[str, str | None]:
    """Build short + detailed tool argument summary for terminal output."""
    if not args:
        return "", None

    highlights: list[str] = []
    file_value = args.get("filePath") or args.get("path") or args.get("file")
    if isinstance(file_value, str):
        file_label = _shorten_workspace_path(file_value)
        start_line = args.get("startLine")
        end_line = args.get("endLine")
        if isinstance(start_line, int) and isinstance(end_line, int):
            highlights.append(f"{file_label} (lines {start_line}-{end_line})")
        else:
            highlights.append(file_label)

    query_value = args.get("query")
    if isinstance(query_value, str) and query_value.strip():
        snippet = query_value.strip().replace("\n", " ")[:80]
        highlights.append(f"query: {snippet}")

    pattern_value = args.get("includePattern")
    if isinstance(pattern_value, str) and pattern_value.strip():
        highlights.append(f"scope: {pattern_value}")

    summary = f" → {' | '.join(highlights)}" if highlights else ""

    # Full JSON for deeper inspection when available.
    try:
        detail = json.dumps(args, ensure_ascii=False)
    except Exception:
        detail = str(args)

    return summary, detail


def _extract_usage_event(event_data: Any) -> dict[str, Any]:
    """Extract normalized token/cost fields from assistant.usage event payload."""
    usage: dict[str, Any] = {
        "model": getattr(event_data, "model", None),
        "api_call_id": getattr(event_data, "api_call_id", None),
        "provider_call_id": getattr(event_data, "provider_call_id", None),
        "initiator": getattr(event_data, "initiator", None),
        "input_tokens": float(getattr(event_data, "input_tokens", 0.0) or 0.0),
        "output_tokens": float(getattr(event_data, "output_tokens", 0.0) or 0.0),
        "cache_read_tokens": float(getattr(event_data, "cache_read_tokens", 0.0) or 0.0),
        "cache_write_tokens": float(getattr(event_data, "cache_write_tokens", 0.0) or 0.0),
        "reasoning_tokens": float(getattr(event_data, "reasoning_tokens", 0.0) or 0.0),
        "cost": float(getattr(event_data, "cost", 0.0) or 0.0),
        "duration": float(getattr(event_data, "duration", 0.0) or 0.0),
    }

    token_details: list[dict[str, Any]] = []
    total_nano_aiu = 0.0
    copilot_usage = getattr(event_data, "copilot_usage", None)
    if copilot_usage is not None:
        total_nano_aiu = float(getattr(copilot_usage, "total_nano_aiu", 0.0) or 0.0)
        for detail in getattr(copilot_usage, "token_details", []) or []:
            token_details.append(
                {
                    "token_type": getattr(detail, "token_type", None),
                    "token_count": float(getattr(detail, "token_count", 0.0) or 0.0),
                    "batch_size": float(getattr(detail, "batch_size", 0.0) or 0.0),
                    "cost_per_batch": float(getattr(detail, "cost_per_batch", 0.0) or 0.0),
                }
            )

    usage["total_nano_aiu"] = total_nano_aiu
    usage["token_details"] = token_details
    usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    return usage


def _summarize_usage_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate one or more assistant.usage events from a single complete() call."""
    totals = {
        "input_tokens": 0.0,
        "output_tokens": 0.0,
        "cache_read_tokens": 0.0,
        "cache_write_tokens": 0.0,
        "reasoning_tokens": 0.0,
        "cost": 0.0,
        "duration": 0.0,
        "total_nano_aiu": 0.0,
    }

    token_detail_totals: dict[str, float] = {}
    model = None
    for event in events:
        if model is None and event.get("model"):
            model = event.get("model")

        totals["input_tokens"] += float(event.get("input_tokens") or 0.0)
        totals["output_tokens"] += float(event.get("output_tokens") or 0.0)
        totals["cache_read_tokens"] += float(event.get("cache_read_tokens") or 0.0)
        totals["cache_write_tokens"] += float(event.get("cache_write_tokens") or 0.0)
        totals["reasoning_tokens"] += float(event.get("reasoning_tokens") or 0.0)
        totals["cost"] += float(event.get("cost") or 0.0)
        totals["duration"] += float(event.get("duration") or 0.0)
        totals["total_nano_aiu"] += float(event.get("total_nano_aiu") or 0.0)

        for detail in event.get("token_details", []):
            token_type = str(detail.get("token_type") or "unknown")
            token_count = float(detail.get("token_count") or 0.0)
            token_detail_totals[token_type] = token_detail_totals.get(token_type, 0.0) + token_count

    totals["total_tokens"] = totals["input_tokens"] + totals["output_tokens"]
    return {
        "provider": _PROVIDER,
        "model": model or _MODEL,
        "usage_event_count": len(events),
        **totals,
        "token_detail_totals": token_detail_totals,
        "usage_events": events,
    }


# -- Copilot provider (github-copilot-sdk) ------------------------------------

async def _async_complete_copilot(prompt: str, streaming: bool = False) -> str:
    """
    Async implementation using github-copilot-sdk.
    Uses the already-authenticated CLI (no manual auth needed).
    """
    from copilot import CopilotClient  # lazy import
    from copilot.session import PermissionHandler
    from copilot.generated.session_events import (
        AssistantMessageData, AssistantMessageDeltaData, SessionIdleData, 
        SessionEventType, ToolExecutionProgressData, ToolExecutionStartData, ToolExecutionCompleteData
    )

    global _LAST_USAGE_SUMMARY
    _LAST_USAGE_SUMMARY = None

    # Use default CopilotClient - it automatically uses the authenticated CLI
    async with CopilotClient() as client:
        # Create session with required permission handler and streaming
        async with await client.create_session(
            on_permission_request=PermissionHandler.approve_all,
            model=_MODEL,
            system_message={"content": _SYSTEM_PROMPT},
            streaming=streaming,
        ) as session:
            
            result: list[str] = []
            usage_events: list[dict[str, Any]] = []
            done = asyncio.Event()

            def on_event(event) -> None:
                match event.type:
                    case SessionEventType.ASSISTANT_MESSAGE_DELTA:
                        if streaming and event.data.delta_content:
                            # For streaming, print delta immediately
                            import sys
                            sys.stdout.write(event.data.delta_content)
                            sys.stdout.flush()
                        # Always collect content for final result
                        if event.data.delta_content:
                            result.append(event.data.delta_content)
                    case SessionEventType.ASSISTANT_MESSAGE:
                        # Always collect full content regardless of streaming mode
                        if event.data.content:
                            result.append(event.data.content)
                    case SessionEventType.TOOL_EXECUTION_START:
                        if streaming:
                            from rich.console import Console
                            console = Console()
                            tool_name = getattr(event.data, "tool_name", "unknown")
                            args = _extract_tool_event_args(event.data)
                            summary, details = _summarize_tool_args(args)
                            tool_info = f"{tool_name}{summary}"
                            console.print(f"\n🔧 [bold cyan]AI is using tool:[/bold cyan] {tool_info}")
                            if details:
                                console.print(f"   [dim]args: {details}[/dim]")
                    case SessionEventType.TOOL_EXECUTION_PROGRESS:
                        if streaming:
                            from rich.console import Console
                            console = Console()
                            console.print(f"📁 [dim]AI tool in progress...[/dim]")
                    case SessionEventType.TOOL_EXECUTION_COMPLETE:
                        if streaming:
                            from rich.console import Console
                            console = Console()
                            console.print(f"✅ [green]Tool completed successfully[/green]")
                    case SessionEventType.ASSISTANT_USAGE:
                        usage_events.append(_extract_usage_event(event.data))
                    case SessionEventType.SESSION_IDLE:
                        if streaming:
                            print()  # New line when done
                        done.set()

            session.on(on_event)
            await session.send(prompt)
            await done.wait()

            _LAST_USAGE_SUMMARY = _summarize_usage_events(usage_events)

            return "".join(result)


def _complete_copilot(prompt: str, streaming: bool = False) -> str:
    """Sync wrapper around the async Copilot SDK call."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already inside an event loop (e.g. Jupyter) -- use a new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _async_complete_copilot(prompt, streaming))
                return future.result()
        return loop.run_until_complete(_async_complete_copilot(prompt, streaming))
    except RuntimeError:
        return asyncio.run(_async_complete_copilot(prompt, streaming))


# -- Alternative providers -----------------------------------------------------

def _complete_openai(prompt: str) -> str:
    from openai import OpenAI  # lazy import

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    global _LAST_USAGE_SUMMARY
    _LAST_USAGE_SUMMARY = None
    return response.choices[0].message.content or ""


def _complete_anthropic(prompt: str) -> str:
    import anthropic  # lazy import

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    global _LAST_USAGE_SUMMARY
    _LAST_USAGE_SUMMARY = None
    return message.content[0].text


_CLAUDE_AGENT_ALLOWED_TOOLS = [
    "Read", "Write", "Edit", "Bash", "Grep", "Glob", "LS",
    "WebSearch", "WebFetch",
]


def _complete_claude_agent(prompt: str, streaming: bool = False) -> str:
    """
    Claude Agent SDK (claude-agent-sdk-python) — mirrors the Copilot provider pattern.
    Uses the bundled Claude Code CLI; auth is read from ~/.claude/ automatically.
    All tools in _CLAUDE_AGENT_ALLOWED_TOOLS are auto-approved; file edits are
    accepted automatically via permission_mode='acceptEdits'.

    Requires:  pip install claude-agent-sdk
    """
    import anyio
    from claude_agent_sdk import (
        query, ClaudeAgentOptions,
        AssistantMessage, UserMessage, ResultMessage,
        TextBlock, ToolUseBlock, ToolResultBlock,
    )
    import sys
    from rich.console import Console

    settings = _load_claude_settings()
    model = _resolve_claude_model(settings)

    options = ClaudeAgentOptions(
        system_prompt=_SYSTEM_PROMPT,
        model=model,
        max_turns=20,
        allowed_tools=_CLAUDE_AGENT_ALLOWED_TOOLS,
        permission_mode="acceptEdits",
    )

    console = Console()
    result: list[str] = []
    global _LAST_USAGE_SUMMARY

    async def _run() -> None:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        if streaming:
                            sys.stdout.write(block.text)
                            sys.stdout.flush()
                        result.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        tool_name = getattr(block, "name", "unknown")
                        tool_input = getattr(block, "input", {}) or {}

                        # Track tool use
                        tracker = get_usage_tracker()
                        if tracker:
                            tracker.record_tool_use(tool_name=tool_name, tool_input=tool_input)

                        if streaming:
                            summary, details = _summarize_tool_args(tool_input)
                            console.print(f"\n🔧 [bold cyan]AI is using tool:[/bold cyan] {tool_name}{summary}")
                            if details:
                                console.print(f"   [dim]args: {details}[/dim]")

            elif isinstance(message, UserMessage):
                # UserMessage wraps ToolResultBlock responses from the agent loop
                if streaming:
                    for block in getattr(message, "content", []):
                        if isinstance(block, ToolResultBlock):
                            is_error = getattr(block, "is_error", False)
                            if is_error:
                                console.print("❌ [red]Tool returned an error[/red]")
                            else:
                                console.print("✅ [green]Tool completed successfully[/green]")

            elif isinstance(message, ResultMessage):
                usage = getattr(message, "usage", None)
                total_cost = getattr(message, "total_cost_usd", None)
                num_turns = getattr(message, "num_turns", 0)
                duration_api_ms = getattr(message, "duration_api_ms", 0)

                if usage:
                    input_tokens = float(getattr(usage, "input_tokens", 0) or 0)
                    output_tokens = float(getattr(usage, "output_tokens", 0) or 0)
                    cache_read = float(getattr(usage, "cache_read_tokens", 0) or 0)
                    cache_write = float(getattr(usage, "cache_write_tokens", 0) or 0)

                    _LAST_USAGE_SUMMARY = {
                        "provider": "claude",
                        "model": model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cache_read_tokens": cache_read,
                        "cache_write_tokens": cache_write,
                        "total_tokens": input_tokens + output_tokens,
                        "total_cost_usd": total_cost or 0.0,
                        "num_turns": num_turns,
                        "usage_event_count": 1,
                    }

                    # Track usage
                    tracker = get_usage_tracker()
                    if tracker:
                        tracker.record_llm_call(
                            provider="claude",
                            model=model,
                            prompt_chars=len(prompt),
                            response_chars=len("".join(result)),
                            usage=_LAST_USAGE_SUMMARY,
                            api_duration_ms=duration_api_ms,
                        )

        if streaming:
            print()  # trailing newline

    try:
        anyio.run(_run)
    except RuntimeError:
        # Already inside an event loop — run in a thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(anyio.run, _run).result()

    return "".join(result)


# -- Public API ----------------------------------------------------------------

def complete(prompt: str, streaming: bool = False) -> str:
    """Send *prompt* to the configured LLM and return the raw text response."""
    log_event(
        "llm.call_started",
        {
            "provider": _PROVIDER,
            "model": _MODEL,
            "streaming": streaming,
            "prompt_chars": len(prompt),
        },
    )
    log_prompt(prompt, label="llm_prompt")

    if _PROVIDER == "anthropic":
        response = _complete_anthropic(prompt)
    elif _PROVIDER == "claude":
        response = _complete_claude_agent(prompt, streaming)
    elif _PROVIDER == "openai":
        response = _complete_openai(prompt)
    else:
        response = _complete_copilot(prompt, streaming)

    usage = _LAST_USAGE_SUMMARY
    log_output(response, label="llm_output")
    log_event(
        "llm.call_completed",
        {
            "provider": _PROVIDER,
            "model": _MODEL,
            "response_chars": len(response),
            "usage_event_count": int((usage or {}).get("usage_event_count") or 0),
            "total_tokens": float((usage or {}).get("total_tokens") or 0.0),
        },
    )
    return response


def get_last_usage_summary() -> dict[str, Any] | None:
    """Return the most recent usage summary captured by complete()."""
    return _LAST_USAGE_SUMMARY


def get_provider_and_model() -> tuple[str, str]:
    """Expose provider/model for usage reporting metadata."""
    return _PROVIDER, _MODEL


def init_llm_session(app_name: str, command_name: str) -> None:
    """Initialize LLM session with usage tracking (call at command start)."""
    init_usage_tracker(app_name, command_name)


def finalize_llm_session() -> Path | None:
    """Finalize LLM session and save usage JSON (call at command end)."""
    return finalize_usage_tracker()
