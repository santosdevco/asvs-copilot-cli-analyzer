"""
commands/triage.py  —  Step 2
──────────────────────────────
Architect Agent: groups source files into high-level security components.

Usage:
  python cli.py triage <app_name> [--dry-run]
"""
from __future__ import annotations

import json
import os
import sys

import click
import pyperclip
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Summary/status output goes to stderr so stdout stays clean for redirection
console = Console(stderr=True)

from cli.config import TRIAGE_PROMPT_FILE
from cli.core import (
    build_triage_context,
    complete,
    complete_interactive,
    get_provider_and_model,
    load_component_index,
    missing_keys,
    render,
    write_usage_report,
    write_component_index,
)
from cli.core.context_builder import _extract_source_dir_from_static
from cli.core.app_logger import init_app_logger, log_event, log_prompt


def _print_dry_run_summary(prompt: str, app_name: str) -> None:
    """Print a config + context-size summary table after a dry-run."""
    chars = len(prompt)
    # rough token estimate: ~4 chars per token for English/code
    tokens_est = chars // 4

    table = Table(title="Dry-run summary", show_header=True, header_style="bold magenta")
    table.add_column("Setting", style="cyan", no_wrap=True)
    table.add_column("Value")

    table.add_row("App", app_name)
    table.add_row("LLM_PROVIDER", os.getenv("LLM_PROVIDER", "copilot"))
    table.add_row("LLM_MODEL", os.getenv("LLM_MODEL", "claude-sonnet-4.6"))
    table.add_row("LLM_MAX_TOKENS", os.getenv("LLM_MAX_TOKENS", "8192"))
    table.add_row("Prompt chars", f"{chars:,}")
    table.add_row("Tokens (est.)", f"~{tokens_est:,}")

    console.print(table)


@click.command("triage")
@click.argument("app_name")
@click.option("--dry-run", is_flag=True, help="Print the rendered prompt without calling the LLM.")
@click.option("--show-prompt", is_flag=True, help="Show full prompt content in dry-run mode.")
@click.option("--verbose", "-v", is_flag=True, help="Show AI's reasoning and internal analysis.")
@click.option("--interactive", "-i", is_flag=True, help="Allow AI to ask questions during analysis.")
@click.option("--streaming", "-s", is_flag=True, help="Stream AI responses in real-time and show file access.")
@click.option(
    "--active-tools",
    default=None,
    help=(
        "Comma-separated list of tools to enable for Claude SDK (e.g., 'Read,Write,Edit'). "
        "Use 'None' to disable all tools. Only applies when LLM_PROVIDER=claude."
    ),
)
@click.option(
    "--copy-clipboard",
    is_flag=True,
    default=False,
    help="Automatically copy the prompt to the clipboard (useful with --dry-run).",
)
def triage_cmd(app_name: str, dry_run: bool, show_prompt: bool, verbose: bool, interactive: bool, streaming: bool, active_tools: str | None, copy_clipboard: bool) -> None:
    """Step 2 — Architect agent: identify components and create context files."""

    # Parse active_tools flag
    parsed_tools: list[str] | None = None
    if active_tools is not None:
        if active_tools.strip().lower() == "none":
            parsed_tools = []
        else:
            parsed_tools = [t.strip() for t in active_tools.split(",") if t.strip()]

    from cli.core import init_llm_session
    init_llm_session(app_name=app_name, command_name="triage", active_tools=parsed_tools)

    init_app_logger(
        app_name=app_name,
        command_name="triage",
        command_line=" ".join(sys.argv),
        options={
            "dry_run": dry_run,
            "show_prompt": show_prompt,
            "verbose": verbose,
            "interactive": interactive,
            "streaming": streaming,
            "active_tools": active_tools,
        },
    )
    console.print(f"[bold cyan]triage[/bold cyan] {app_name}")

    if active_tools is not None:
        tools_display = "none" if not parsed_tools else ", ".join(parsed_tools)
        console.print(f"[dim]Active tools: {tools_display}[/dim]")

    # ── Build context and render prompt ──────────────────────────────────────
    ctx = build_triage_context(app_name)
    template = TRIAGE_PROMPT_FILE.read_text(encoding="utf-8")

    absent = missing_keys(template, ctx)
    if absent:
        console.print(f"[yellow]Warning: unresolved placeholders: {absent}[/yellow]")

    prompt = render(template, ctx)
    log_prompt(prompt, label="triage_prompt")

    if dry_run or show_prompt:
        log_event("triage.dry_run", {"prompt_chars": len(prompt)})
        if copy_clipboard:
            try:
                pyperclip.copy(prompt)
                console.print("[green]✅ Prompt copied to clipboard[/green]")
            except Exception as e:
                console.print(f"[yellow]⚠ Could not copy to clipboard: {e}[/yellow]")
        if show_prompt:
            sys.stdout.write(prompt)
            sys.stdout.write("\n")
            sys.stdout.flush()
        _print_dry_run_summary(prompt, app_name)
        return

    # ── Call LLM ──────────────────────────────────────────────────────────────
    console.print("Sending prompt to LLM…")

    usage_summary = {}
    if verbose or interactive or streaming:
        usage_summary, response = complete_interactive(
            prompt,
            verbose=verbose,
            interactive=interactive,
            streaming=streaming,
            context=f"Triage analysis for {app_name}"
        )
    else:
        # Standard non-interactive mode
        response = complete(prompt)

    log_event(
        "triage.response",
        {
            "response_chars": len(response),
            "usage_captured": bool(usage_summary),
        },
    )

    # ── Load outputs written by the agent directly to disk ───────────────────
    try:
        index = load_component_index(app_name)
        if not index.source_dir_path:
            index.source_dir_path = _extract_source_dir_from_static(app_name) or None
            write_component_index(app_name, index)
    except FileNotFoundError as exc:
        console.print(f"[bold red]✗ Triage did not produce components/index.json: {exc}[/bold red]")
        console.print("[dim]Raw response saved to /tmp/triage_response.txt[/dim]")
        import pathlib
        pathlib.Path("/tmp/triage_response.txt").write_text(response, encoding="utf-8")
        raise SystemExit(1)

    # ── Report outputs already persisted by the agent ────────────────────────
    for component in index.project_triage:
        cid = component.component_id
        console.print(f"[green]  ✓ component detected → {cid}[/green]")

    provider, model = get_provider_and_model()
    usage_calls = [
        {
            "operation": "triage",
            "prompt_chars": len(prompt),
            "response_chars": len(response),
            "usage": usage_summary,
        }
    ]
    usage_path = write_usage_report(
        app_name=app_name,
        command_name="triage",
        calls=usage_calls,
        provider=provider,
        model=model,
        metadata={"components_identified": len(index.project_triage)},
    )
    if usage_summary and usage_summary.get("usage_event_count", 0) > 0:
        total_tokens = usage_summary.get("total_tokens", 0.0)
        console.print(f"[cyan]📊 Token usage saved → {usage_path} (total={total_tokens:.0f})[/cyan]")
    else:
        console.print(f"[yellow]⚠ No assistant usage events captured; report still written → {usage_path}[/yellow]")

    console.print(f"[bold green]Triage complete — {len(index.project_triage)} component(s) identified.[/bold green]")
