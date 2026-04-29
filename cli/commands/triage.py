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
    get_last_usage_summary,
    get_provider_and_model,
    missing_keys,
    parse_json,
    render,
    write_component_context,
    write_component_index,
    write_usage_report,
)
from cli.models import ComponentIndex
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


def _extract_context_map(raw_response: str) -> dict[str, str]:
    """
    The LLM is asked to return a JSON object with two keys:
      {
        "index": { ... ComponentIndex ... },
        "contexts": { "<component_id>": "<context.xml content>" }
      }
    Returns a mapping of component_id → context XML text.
    """
    data = parse_json(raw_response)
    return data.get("contexts", {})


@click.command("triage")
@click.argument("app_name")
@click.option("--dry-run", is_flag=True, help="Print the rendered prompt without calling the LLM.")
@click.option("--show-prompt", is_flag=True, help="Show full prompt content in dry-run mode.")
@click.option("--verbose", "-v", is_flag=True, help="Show AI's reasoning and internal analysis.")
@click.option("--interactive", "-i", is_flag=True, help="Allow AI to ask questions during analysis.")
@click.option("--streaming", "-s", is_flag=True, help="Stream AI responses in real-time and show file access.")
def triage_cmd(app_name: str, dry_run: bool, show_prompt: bool, verbose: bool, interactive: bool, streaming: bool) -> None:
    """Step 2 — Architect agent: identify components and create context files."""
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
        },
    )
    console.print(f"[bold cyan]triage[/bold cyan] {app_name}")

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
        if show_prompt:
            sys.stdout.write(prompt)
            sys.stdout.write("\n")
            sys.stdout.flush()
        _print_dry_run_summary(prompt, app_name)
        return

    # ── Call LLM ──────────────────────────────────────────────────────────────
    console.print("Sending prompt to LLM…")
    
    if verbose or interactive or streaming:
        # Use interactive client for enhanced experience
        parsed_data, response = complete_interactive(
            prompt, 
            verbose=verbose, 
            interactive=interactive,
            streaming=streaming,
            context=f"Triage analysis for {app_name}"
        )
        data = parsed_data
    else:
        # Standard non-interactive mode
        response = complete(prompt)
        data = parse_json(response)

    usage_summary = get_last_usage_summary()
    log_event(
        "triage.response",
        {
            "response_chars": len(response),
            "usage_captured": bool(usage_summary),
        },
    )

    # ── Parse response ────────────────────────────────────────────────────────
    # Expected shape:
    # {
    #   "index": <ComponentIndex JSON>,
    #   "contexts": { "<component_id>": "<context.xml text>", … }
    # }
    try:
        # If we used interactive/streaming mode, data is already parsed
        # Otherwise, we need to parse the raw response
        if (verbose or interactive or streaming):
            # data is already parsed from complete_interactive()
            pass  
        else:
            # Parse raw response for standard mode
            data = parse_json(response)
            
        index = ComponentIndex.model_validate(data["index"])
        contexts: dict[str, str] = data.get("contexts", {})
    except (KeyError, ValueError) as exc:
        console.print(f"[bold red]✗ Failed to parse LLM response: {exc}[/bold red]")
        console.print("[dim]Raw response saved to /tmp/triage_response.txt[/dim]")
        import tempfile, pathlib
        pathlib.Path("/tmp/triage_response.txt").write_text(response, encoding="utf-8")
        raise SystemExit(1)

    # ── Persist outputs ───────────────────────────────────────────────────────
    index_path = write_component_index(app_name, index)
    console.print(f"[green]✓ index.json → {index_path}[/green]")

    for component in index.project_triage:
        cid = component.component_id
        ctx_content = contexts.get(cid, "")
        if not ctx_content:
            console.print(f"[yellow]  ⚠ No context.xml content returned for '{cid}'[/yellow]")
            continue
        ctx_path = write_component_context(app_name, cid, ctx_content)
        console.print(f"[green]  ✓ context.xml → {ctx_path}[/green]")

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
