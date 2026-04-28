"""
commands/audit.py  —  Step 4
─────────────────────────────
Specialized Audit Loop: one agent call per (component × ASVS chapter).

Usage:
  python cli.py audit <app_name>
  python cli.py audit <app_name> --component auth_and_session_module
  python cli.py audit <app_name> --component auth_and_session_module --chapter V6
  python cli.py audit <app_name> --dry-run
"""
from __future__ import annotations

import os
from pathlib import Path
import json
import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from rich.table import Table

from cli.config import AUDIT_PROMPT_FILE
from cli.core import (
    build_audit_context,
    complete,
    complete_interactive,
    get_last_usage_summary,
    get_provider_and_model,
    get_applicable_asvs_keys,
    load_component_index,
    missing_keys,
    render,
    write_usage_report,
)
from cli.models import ComponentItem
from cli.core.app_logger import init_app_logger, log_event, log_prompt

console = Console()


def _write_audit_usage_report(app_name: str, usage_calls: list[dict]) -> None:
    """Persist usage report for this audit command execution."""
    if not usage_calls:
        return

    provider, model = get_provider_and_model()
    usage_path = write_usage_report(
        app_name=app_name,
        command_name="audit",
        calls=usage_calls,
        provider=provider,
        model=model,
        metadata={"audit_calls": len(usage_calls)},
    )

    total_tokens = 0.0
    for call in usage_calls:
        usage = call.get("usage") or {}
        total_tokens += float(usage.get("total_tokens") or 0.0)
    console.print(f"[cyan]📊 Audit token usage saved → {usage_path} (total={total_tokens:.0f})[/cyan]")


def _print_call_usage(call_usage: dict | None) -> None:
    """Print per-call usage summary when available."""
    if not call_usage:
        return

    usage = call_usage.get("usage") or {}
    if not usage:
        console.print("[yellow]⚠ No assistant.usage event received for this call.[/yellow]")
        return

    input_tokens = float(usage.get("input_tokens") or 0.0)
    output_tokens = float(usage.get("output_tokens") or 0.0)
    total_tokens = float(usage.get("total_tokens") or (input_tokens + output_tokens))
    usage_events = int(usage.get("usage_event_count") or 0)
    console.print(
        "[cyan]📈 Call usage:[/cyan] "
        f"input={input_tokens:.0f} output={output_tokens:.0f} total={total_tokens:.0f} "
        f"events={usage_events}"
    )


def _scan_existing_analyses(app_name: str) -> dict[str, dict[str, dict]]:
    """Scan for existing analysis files and return progress data."""
    analyses = {}
    components_dir = Path(f"outputs/{app_name}/components")
    
    if not components_dir.exists():
        return {}
    
    for component_dir in components_dir.iterdir():
        if not component_dir.is_dir() or component_dir.name in ['README.md', 'index.json']:
            continue
        
        component_id = component_dir.name
        analyses[component_id] = {}
        
        analysis_dir = component_dir / "analysis"
        if analysis_dir.exists():
            for analysis_file in analysis_dir.glob("*.json"):
                chapter = analysis_file.stem  # V1, V2, etc.
                try:
                    with open(analysis_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        # Count issues
                        issues = len([r for r in data.get('audit_results', []) if r.get('status') == 'FAIL'])
                        analyses[component_id][chapter] = {
                            'file': analysis_file,
                            'issues': issues,
                            'total_checks': len(data.get('audit_results', []))
                        }
                except Exception:
                    continue
    
    return analyses


def _show_progress_summary(components: list[ComponentItem], analyses: dict) -> None:
    """Show overall progress summary."""
    total_possible = 0
    total_completed = 0
    total_issues = 0
    
    for component in components:
        applicable_chapters = get_applicable_asvs_keys(component.asset_tags)
        total_possible += len(applicable_chapters)
        
        component_analyses = analyses.get(component.component_id, {})
        completed = len(component_analyses)
        total_completed += completed
        
        for chapter_data in component_analyses.values():
            total_issues += chapter_data['issues']
    
    progress_pct = (total_completed / total_possible * 100) if total_possible > 0 else 0
    
    console.print(Panel(
        f"[bold cyan]Security Audit Progress[/bold cyan]\n\n"
        f"📊 [bold]{total_completed}/{total_possible}[/bold] chapters analyzed ([cyan]{progress_pct:.1f}%[/cyan])\n"
        f"🚨 [bold red]{total_issues}[/bold red] total security issues found\n"
        f"🔍 [bold]{len(components)}[/bold] components available for analysis",
        border_style="cyan"
    ))


def _select_component_interactive(components: list[ComponentItem], analyses: dict) -> ComponentItem | None:
    """Show component selection menu."""
    console.print("\n[bold cyan]📋 Select Component to Audit:[/bold cyan]")
    
    # Create table with component info
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", style="cyan", width=3)
    table.add_column("Component", style="bold")
    table.add_column("Risk Level", justify="center")
    table.add_column("Asset Tags", style="dim")
    table.add_column("Progress", justify="center")
    
    for i, component in enumerate(components, 1):
        applicable_chapters = get_applicable_asvs_keys(component.asset_tags)
        component_analyses = analyses.get(component.component_id, {})
        completed = len(component_analyses)
        total = len(applicable_chapters)
        
        # Color risk level
        risk_color = {
            "CRITICAL": "red",
            "HIGH": "yellow", 
            "MEDIUM": "blue",
            "LOW": "green"
        }.get(component.risk_level, "white")
        
        progress_text = f"{completed}/{total}"
        if completed > 0:
            progress_text += f" ({completed/total*100:.0f}%)"
        
        table.add_row(
            str(i),
            component.component_name[:40],
            f"[{risk_color}]{component.risk_level}[/{risk_color}]",
            ", ".join(component.asset_tags[:2]),
            progress_text
        )
    
    console.print(table)
    
    # Get selection
    choice = Prompt.ask(
        "\nEnter component number (or 'q' to quit)", 
        choices=[str(i) for i in range(1, len(components) + 1)] + ['q']
    )
    log_event("audit.component_choice", {"choice": choice})
    
    if choice == 'q':
        return None
    
    return components[int(choice) - 1]


def _select_chapter_interactive(component: ComponentItem, analyses: dict) -> str | None:
    """Show chapter selection menu for a component."""
    applicable_chapters = get_applicable_asvs_keys(component.asset_tags)
    component_analyses = analyses.get(component.component_id, {})
    
    console.print(f"\n[bold cyan]📖 ASVS Chapters for {component.component_name}:[/bold cyan]")
    
    # Create table with chapter info
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", style="cyan", width=3)
    table.add_column("Chapter", style="bold")
    table.add_column("Title", style="dim")
    table.add_column("Status", justify="center")
    
    chapter_map = {}
    for i, asvs_key in enumerate(applicable_chapters, 1):
        chapter_id = asvs_key.split("_")[0]
        chapter_title = asvs_key.split("_", 1)[1].replace("_", " ") if "_" in asvs_key else "Unknown"
        
        # Check if completed
        if chapter_id in component_analyses:
            issues = component_analyses[chapter_id]['issues']
            if issues == 0:
                status = "[green]✅ CLEAN[/green]"
            else:
                status = f"[yellow]⚠️ {issues} issues[/yellow]"
        else:
            status = "[dim]⏳ Pending[/dim]"
        
        table.add_row(
            str(i),
            chapter_id,
            chapter_title[:40],
            status
        )
        chapter_map[str(i)] = asvs_key
    
    console.print(table)
    
    # Get selection
    choice = Prompt.ask(
        "\nEnter chapter number (or 'b' for back, 'q' to quit)", 
        choices=list(chapter_map.keys()) + ['b', 'q']
    )
    log_event(
        "audit.chapter_choice",
        {"component_id": component.component_id, "choice": choice},
    )
    
    if choice in ['q', 'b']:
        return choice
    
    return chapter_map[choice]


def _target_components(
    app_name: str,
    component_filter: str | None,
) -> list[ComponentItem]:
    index = load_component_index(app_name)
    if component_filter:
        matches = [c for c in index.project_triage if c.component_id == component_filter]
        if not matches:
            available = [c.component_id for c in index.project_triage]
            console.print(f"[bold red]Component '{component_filter}' not found.[/bold red]")
            console.print(f"Available: {available}")
            raise SystemExit(1)
        return matches
    return index.project_triage


def _target_chapters(
    asset_tags: list[str],
    chapter_filter: str | None,
) -> list[str]:
    """Return ASVS chapter keys applicable to *asset_tags*, optionally filtered."""
    keys = get_applicable_asvs_keys(asset_tags)
    if chapter_filter:
        # Allow short form ("V6") or full key ("V6_Authentication")
        # Fix: Use exact match for chapter number to avoid V1 matching V10, V11, etc.
        if chapter_filter.startswith('V') and len(chapter_filter) <= 3:
            # For "V1", "V2", etc., match exactly "V1_" pattern
            keys = [k for k in keys if k.split('_')[0] == chapter_filter]
        else:
            # For full key names
            keys = [k for k in keys if k.startswith(chapter_filter)]
        if not keys:
            console.print(f"[bold red]No applicable chapter matching '{chapter_filter}'.[/bold red]")
            raise SystemExit(1)
    return keys


@click.command("audit")
@click.argument("app_name")
@click.option("--component", "component_filter", default=None, help="Audit a single component ID.")
@click.option("--chapter", "chapter_filter", default=None, help="Restrict to one ASVS chapter (e.g. V6).")
@click.option("--dry-run", is_flag=True, help="Print rendered prompts without calling the LLM.")
@click.option("--show-prompt", is_flag=True, help="Show full prompt content in dry-run mode.")
@click.option("--verbose", "-v", is_flag=True, help="Show AI's reasoning and internal analysis.")
@click.option("--interactive", "-i", is_flag=True, help="Allow AI to ask questions during analysis.")
@click.option("--streaming", "-s", is_flag=True, help="Stream AI responses in real-time and show file access.")
@click.option(
    "--include-auditor-diary/--no-include-auditor-diary",
    default=True,
    show_default=True,
    help="Include the AUDITOR DIARY section from context.md in the prompt.",
)
def audit_cmd(
    app_name: str,
    component_filter: str | None,
    chapter_filter: str | None,
    dry_run: bool,
    show_prompt: bool,
    verbose: bool,
    interactive: bool,
    streaming: bool,
    include_auditor_diary: bool,
) -> None:
    """Step 4 — Interactive security audit with progress tracking."""
    init_app_logger(
        app_name=app_name,
        command_name="audit",
        command_line=" ".join(sys.argv),
        options={
            "component": component_filter,
            "chapter": chapter_filter,
            "dry_run": dry_run,
            "show_prompt": show_prompt,
            "verbose": verbose,
            "interactive": interactive,
            "streaming": streaming,
            "include_auditor_diary": include_auditor_diary,
        },
    )
    console.print(f"[bold cyan]🔒 Security Audit[/bold cyan] {app_name}")
    usage_calls: list[dict] = []

    # Load components and scan existing analyses
    components = _target_components(app_name, component_filter)
    analyses = _scan_existing_analyses(app_name)
    
    if not components:
        console.print("[bold red]No components found. Run triage first.[/bold red]")
        return

    # If both component and chapter are specified, run directly
    if component_filter and chapter_filter:
        selected_component = components[0]  # Already filtered by _target_components
        applicable_chapters = get_applicable_asvs_keys(selected_component.asset_tags)
        
        # Find matching chapter
        matching_chapters = [k for k in applicable_chapters if k.startswith(chapter_filter)]
        if not matching_chapters:
            console.print(f"[bold red]Chapter {chapter_filter} not applicable to {component_filter}[/bold red]")
            return

        call_usage = _run_audit(
            app_name,
            selected_component,
            matching_chapters[0],
            dry_run,
            show_prompt,
            verbose,
            interactive,
            streaming,
            include_auditor_diary,
        )
        if call_usage:
            usage_calls.append(call_usage)
            _print_call_usage(call_usage)
        _write_audit_usage_report(app_name, usage_calls)
        return

    # Interactive mode
    while True:
        console.clear()
        console.print(f"[bold cyan]🔒 Security Audit[/bold cyan] {app_name}")
        
        # Reload components if filter changed
        components = _target_components(app_name, component_filter)
        _show_progress_summary(components, analyses)
        
        # If component specified, go to chapter selection
        if component_filter:
            selected_component = components[0]  # Already filtered
            result = _select_chapter_interactive(selected_component, analyses)
            
            if result == 'q':
                break
            elif result == 'b':
                component_filter = None  # Go back to component selection
                continue
            else:
                call_usage = _run_audit(
                    app_name,
                    selected_component,
                    result,
                    dry_run,
                    show_prompt,
                    verbose,
                    interactive,
                    streaming,
                    include_auditor_diary,
                )
                if call_usage:
                    usage_calls.append(call_usage)
                    _print_call_usage(call_usage)
                    _write_audit_usage_report(app_name, usage_calls)
                
                # Refresh analyses after audit
                analyses = _scan_existing_analyses(app_name)
                
                if not Confirm.ask("\nRun another audit?"):
                    break
        else:
            # Component selection
            selected_component = _select_component_interactive(components, analyses)
            
            if selected_component is None:
                break
            
            component_filter = selected_component.component_id

    _write_audit_usage_report(app_name, usage_calls)


def _run_audit(
    app_name: str,
    component: ComponentItem,
    asvs_key: str,
    dry_run: bool,
    show_prompt: bool,
    verbose: bool,
    interactive: bool,
    streaming: bool,
    include_auditor_diary: bool,
) -> dict | None:
    """Execute a single audit."""
    chapter_id = asvs_key.split("_")[0]
    label = f"{component.component_id} → {chapter_id}"
    
    console.print(f"\n[bold yellow]🔍 Auditing {label}[/bold yellow]")
    
    # Build and render prompt
    try:
        ctx = build_audit_context(
            app_name,
            component.component_id,
            asvs_key,
            include_auditor_diary=include_auditor_diary,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]⚠ Skipped — {exc}[/red]")
        return None

    template = AUDIT_PROMPT_FILE.read_text(encoding="utf-8")
    absent = missing_keys(template, ctx)
    if absent:
        console.print(f"[yellow]⚠ Unresolved placeholders: {absent}[/yellow]")

    prompt = render(template, ctx)
    log_prompt(prompt, label=f"audit_prompt_{component.component_id}_{chapter_id}")
    log_event(
        "audit.call_started",
        {
            "app_name": app_name,
            "component_id": component.component_id,
            "asvs_key": asvs_key,
            "dry_run": dry_run,
            "verbose": verbose,
            "interactive": interactive,
            "streaming": streaming,
            "include_auditor_diary": include_auditor_diary,
        },
    )

    if dry_run:
        chars = len(prompt)
        tokens_est = chars // 4
        console.print(f"[dim]chars={chars:,}  tokens≈{tokens_est:,}[/dim]")
        
        if show_prompt:
            console.print(Panel(
                prompt,
                title=f"[cyan]{chapter_id} Audit Prompt for {component.component_id}[/cyan]",
                border_style="cyan"
            ))
        return None

    # Call LLM
    console.print("🤖 Calling AI for security analysis...")
    try:
        if verbose or interactive or streaming:
            parsed_result, response = complete_interactive(
                prompt, 
                verbose=verbose, 
                interactive=interactive,
                streaming=streaming,
                context=f"ASVS {chapter_id} audit for {component.component_id}"
            )
        else:
            response = complete(prompt)

        usage_summary = get_last_usage_summary()
        log_event(
            "audit.call_completed",
            {
                "component_id": component.component_id,
                "asvs_key": asvs_key,
                "response_chars": len(response),
                "usage_captured": bool(usage_summary),
            },
        )
        
        console.print(f"[green]✅ Analysis complete for {label}[/green]")
        return {
            "operation": "audit",
            "component_id": component.component_id,
            "asvs_key": asvs_key,
            "prompt_chars": len(prompt),
            "response_chars": len(response),
            "usage": usage_summary,
        }
        
    except Exception as exc:
        usage_summary = get_last_usage_summary()
        log_event(
            "audit.call_failed",
            {
                "component_id": component.component_id,
                "asvs_key": asvs_key,
                "error": str(exc),
                "usage_captured": bool(usage_summary),
            },
        )

        if usage_summary:
            total_tokens = float(usage_summary.get("total_tokens") or 0.0)
            console.print(
                f"[yellow]⚠ Analysis output parsing failed, but usage was captured (total={total_tokens:.0f}).[/yellow]"
            )
            return {
                "operation": "audit_failed_output_parse",
                "component_id": component.component_id,
                "asvs_key": asvs_key,
                "prompt_chars": len(prompt),
                "response_chars": 0,
                "usage": usage_summary,
                "error": str(exc),
            }

        console.print(f"[bold red]❌ Failed: {exc}[/bold red]")
        return None
