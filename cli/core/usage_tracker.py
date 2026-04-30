"""
usage_tracker.py
────────────────
Tracks LLM API usage and costs, writing JSON files similar to Copilot's app/usage/*.json format.
Each execution generates a detailed usage file with tokens, costs, tool uses, and timing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid

from cli.config import OUTPUTS_DIR


class UsageTracker:
    """Tracks and persists LLM usage metrics to JSON files."""

    def __init__(self, app_name: str, command_name: str):
        self.app_name = app_name
        self.command_name = command_name
        self.session_id = str(uuid.uuid4())
        self.start_time = datetime.now(timezone.utc)

        # Usage directory: outputs/<app_name>/usage/
        self.usage_dir = OUTPUTS_DIR / app_name / "usage"
        self.usage_dir.mkdir(parents=True, exist_ok=True)

        # Accumulated metrics
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_cache_write_tokens = 0
        self.total_cost_usd = 0.0
        self.total_duration_ms = 0
        self.total_api_duration_ms = 0
        self.num_llm_calls = 0
        self.num_turns = 0
        self.tool_uses: list[dict[str, Any]] = []
        self.llm_calls: list[dict[str, Any]] = []

    def record_tool_use(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_result: Any | None = None,
        is_error: bool = False,
        duration_ms: float = 0,
    ) -> None:
        """Record a tool execution."""
        self.tool_uses.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_result": str(tool_result)[:500] if tool_result else None,  # Truncate large results
            "is_error": is_error,
            "duration_ms": duration_ms,
        })

    def record_llm_call(
        self,
        provider: str,
        model: str,
        prompt_chars: int,
        response_chars: int,
        usage: dict[str, Any] | None = None,
        duration_ms: float = 0,
        api_duration_ms: float = 0,
    ) -> None:
        """Record an LLM API call with detailed usage metrics."""
        self.num_llm_calls += 1

        if usage:
            input_tokens = int(usage.get("input_tokens", 0))
            output_tokens = int(usage.get("output_tokens", 0))
            cache_read = int(usage.get("cache_read_tokens", 0))
            cache_write = int(usage.get("cache_write_tokens", 0))
            cost_usd = float(usage.get("cost", 0.0) or usage.get("total_cost_usd", 0.0))
            num_turns = int(usage.get("num_turns", 0))

            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.total_cache_read_tokens += cache_read
            self.total_cache_write_tokens += cache_write
            self.total_cost_usd += cost_usd
            self.num_turns = max(self.num_turns, num_turns)
        else:
            input_tokens = 0
            output_tokens = 0
            cache_read = 0
            cache_write = 0
            cost_usd = 0.0

        self.total_duration_ms += duration_ms
        self.total_api_duration_ms += api_duration_ms

        call_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provider": provider,
            "model": model,
            "prompt_chars": prompt_chars,
            "response_chars": response_chars,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "total_tokens": input_tokens + output_tokens,
            "cost_usd": cost_usd,
            "duration_ms": duration_ms,
            "api_duration_ms": api_duration_ms,
        }

        # Add token details if available (from Copilot provider)
        if usage and "token_detail_totals" in usage:
            call_record["token_detail_totals"] = usage["token_detail_totals"]

        self.llm_calls.append(call_record)

    def finalize(self) -> Path:
        """Write final usage summary to JSON file and return the path."""
        end_time = datetime.now(timezone.utc)
        execution_duration_ms = int((end_time - self.start_time).total_seconds() * 1000)

        # Generate filename: usage_<timestamp>_<session_id_short>.json
        timestamp_str = self.start_time.strftime("%Y%m%d_%H%M%S")
        session_short = self.session_id[:8]
        filename = f"usage_{timestamp_str}_{session_short}.json"
        usage_file = self.usage_dir / filename

        summary = {
            "session_id": self.session_id,
            "app_name": self.app_name,
            "command": self.command_name,
            "start_time": self.start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "execution_duration_ms": execution_duration_ms,

            # Aggregated metrics
            "summary": {
                "total_llm_calls": self.num_llm_calls,
                "total_turns": self.num_turns,
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_tokens": self.total_input_tokens + self.total_output_tokens,
                "total_cache_read_tokens": self.total_cache_read_tokens,
                "total_cache_write_tokens": self.total_cache_write_tokens,
                "total_cost_usd": round(self.total_cost_usd, 6),
                "total_duration_ms": self.total_duration_ms,
                "total_api_duration_ms": self.total_api_duration_ms,
                "total_tool_uses": len(self.tool_uses),
            },

            # Detailed records
            "llm_calls": self.llm_calls,
            "tool_uses": self.tool_uses,
        }

        with usage_file.open("w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        return usage_file


# Global tracker instance for the current session
_current_tracker: UsageTracker | None = None


def init_usage_tracker(app_name: str, command_name: str) -> UsageTracker:
    """Initialize a new usage tracker for the current execution."""
    global _current_tracker
    _current_tracker = UsageTracker(app_name, command_name)
    return _current_tracker


def get_usage_tracker() -> UsageTracker | None:
    """Get the current usage tracker instance."""
    return _current_tracker


def finalize_usage_tracker() -> Path | None:
    """Finalize and persist the current usage tracker."""
    global _current_tracker
    if _current_tracker is None:
        return None

    usage_file = _current_tracker.finalize()
    _current_tracker = None
    return usage_file
