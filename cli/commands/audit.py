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
from cli.core.llm_client import init_llm_session, finalize_llm_session
from cli.core.grouped_audit import (
    build_grouped_worklist,
    run_grouped_by_chapter_job,
    run_grouped_by_component_job,
    get_tag_chapter_stats,
    get_pending_components_for_tag_chapter,
    get_asvs_key_for_chapter,
    TagStats,
)
from cli.models import ComponentItem
from cli.core.app_logger import init_app_logger, log_event, log_prompt

# Summary/status output goes to stderr so stdout stays clean for redirection
console = Console(stderr=True)


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
            for analysis_file in analysis_dir.glob("*.xml"):
                chapter = analysis_file.stem  # V1, V2, etc.
                try:
                    import xml.etree.ElementTree as ET
                    root = ET.parse(analysis_file).getroot()
                    reqs = root.findall("requirements/requirement")
                    issues = sum(1 for r in reqs if r.get("status") == "FAIL")
                    analyses[component_id][chapter] = {
                        'file': analysis_file,
                        'issues': issues,
                        'total_checks': len(reqs)
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


def _pct(done: int, total: int) -> str:
    if total == 0:
        return "—"
    p = done / total * 100
    color = "green" if p == 100 else ("yellow" if p > 0 else "dim")
    return f"[{color}]{done}/{total} ({p:.0f}%)[/{color}]"


def _summarize_component_ids(components: list[ComponentItem], limit: int = 4) -> str:
    """Render a compact component-id list for interactive tables."""
    component_ids = [component.component_id for component in components]
    if not component_ids:
        return "[green]none[/green]"
    if len(component_ids) <= limit:
        return ", ".join(component_ids)
    shown = ", ".join(component_ids[:limit])
    return f"{shown} (+{len(component_ids) - limit})"


def _select_tag_interactive(
    tag_stats: dict[str, "TagStats"],
) -> str | None:
    """Show asset-tag selection table; return chosen tag or None to quit."""
    tags = sorted(tag_stats.keys())
    table = Table(show_header=True, header_style="bold magenta",
                  title="[bold cyan]📦 Asset Tags — Select a group to audit[/bold cyan]")
    table.add_column("#", style="cyan", width=3)
    table.add_column("Asset Tag", style="bold")
    table.add_column("Components", justify="right")
    table.add_column("Progress (pairs)", justify="center")
    table.add_column("Pending chapters", style="dim")

    for i, tag in enumerate(tags, 1):
        ts = tag_stats[tag]
        pending = ts.pending_chapters
        table.add_row(
            str(i),
            tag,
            str(sum(v["total"] for v in ts.chapters.values())),
            _pct(ts.completed_pairs, ts.total_pairs),
            ", ".join(sorted(pending)) if pending else "[green]all done[/green]",
        )

    console.print(table)
    choice = Prompt.ask(
        "\nEnter tag number (or 'q' to quit)",
        choices=[str(i) for i in range(1, len(tags) + 1)] + ["q"],
    )
    if choice == "q":
        return None
    return tags[int(choice) - 1]


def _select_chapter_for_tag(
    app_name: str,
    tag: str,
    tag_stats: dict[str, "TagStats"],
    override: bool,
) -> str | None:
    """Show chapter selection for a given tag; return chapter_id or None to go back."""
    ts = tag_stats[tag]
    chapters = sorted(ts.chapters.keys())
    table = Table(show_header=True, header_style="bold magenta",
                  title=f"[bold cyan]📖 Chapters for tag:[/bold cyan] [yellow]{tag}[/yellow]")
    table.add_column("#", style="cyan", width=3)
    table.add_column("Chapter", style="bold")
    table.add_column("Progress", justify="center")
    table.add_column("Pending components", justify="right")
    table.add_column("Components", style="dim")

    for i, ch in enumerate(chapters, 1):
        v = ts.chapters[ch]
        pending = v["total"] - v["completed"]
        asvs_key = get_asvs_key_for_chapter(ch)
        chapter_components = get_pending_components_for_tag_chapter(app_name, tag, asvs_key, override)
        table.add_row(
            str(i),
            ch,
            _pct(v["completed"], v["total"]),
            str(pending) if pending > 0 else "[green]0[/green]",
            _summarize_component_ids(chapter_components),
        )

    console.print(table)
    choice = Prompt.ask(
        "\nEnter chapter number (or 'b' to go back, 'q' to quit)",
        choices=[str(i) for i in range(1, len(chapters) + 1)] + ["b", "q"],
    )
    if choice in ("b", "q"):
        return choice
    return chapters[int(choice) - 1]


def _run_asset_tags_interactive(
    app_name: str,
    override: bool,
    dry_run: bool,
    show_prompt: bool,
    verbose: bool,
    interactive: bool,
    streaming: bool,
    include_auditor_diary: bool,
    usage_calls: list[dict],
) -> None:
    """Full interactive loop for --group-by asset_tags."""
    common_kwargs = dict(
        dry_run=dry_run,
        show_prompt=show_prompt,
        verbose=verbose,
        interactive=interactive,
        streaming=streaming,
        include_auditor_diary=include_auditor_diary,
    )

    while True:
        console.clear()
        console.print(f"[bold cyan]🔒 Security Audit[/bold cyan] {app_name}  "
                      f"[yellow]group-by: asset_tags[/yellow]"
                      + ("  [dim](override)[/dim]" if override else ""))

        tag_stats = get_tag_chapter_stats(app_name, override=override)
        if not tag_stats:
            console.print("[red]No components found. Run triage first.[/red]")
            return

        tag = _select_tag_interactive(tag_stats)
        if tag is None:
            break

        while True:
            console.clear()
            console.print(f"[bold cyan]🔒 Security Audit[/bold cyan] {app_name}  "
                          f"[yellow]tag: {tag}[/yellow]")

            # Refresh stats so chapter progress reflects any just-completed runs
            tag_stats = get_tag_chapter_stats(app_name, override=override)
            result = _select_chapter_for_tag(app_name, tag, tag_stats, override)

            if result == "q":
                return
            if result == "b":
                break

            chapter_id = result
            try:
                asvs_key = get_asvs_key_for_chapter(chapter_id)
            except KeyError as exc:
                console.print(f"[red]{exc}[/red]")
                continue

            pending = get_pending_components_for_tag_chapter(app_name, tag, asvs_key, override)
            if not pending:
                console.print(
                    f"[green]✓ All components for tag '{tag}' / {chapter_id} already analysed.[/green]\n"
                    "  Use [bold]--override[/bold] to force re-run."
                )
                Prompt.ask("Press Enter to continue", default="")
                continue

            console.print(
                f"\n[bold]Running grouped audit:[/bold] tag=[cyan]{tag}[/cyan]  "
                f"chapter=[cyan]{chapter_id}[/cyan]  "
                f"components=[cyan]{len(pending)}[/cyan]"
            )

            results = run_grouped_by_chapter_job(app_name, asvs_key, pending, **common_kwargs)
            usage_calls.extend(r for r in results if r.get("usage"))

            if not dry_run:
                console.print(
                    f"\n[bold green]✓ Done:[/bold green] "
                    f"{len(results)} file(s) written for {chapter_id} / tag '{tag}'"
                )

            if not Confirm.ask("\nRun another chapter for this tag?"):
                break

        if not Confirm.ask("\nSelect another tag?"):
            break


def _run_grouped_audit(
    app_name: str,
    group_by: str,
    component_filter: str | None,
    chapter_filter: str | None,
    override: bool,
    dry_run: bool,
    show_prompt: bool,
    verbose: bool,
    interactive: bool,
    streaming: bool,
    include_auditor_diary: bool,
    usage_calls: list[dict],
) -> None:
    """Delegate to grouped runners and collect usage records."""
    mode_label = {"asvs_chapter": "per chapter", "asset_tags": "per tag × chapter", "component": "per component"}
    console.print(
        f"[bold cyan]Group-by:[/bold cyan] [yellow]{group_by}[/yellow] "
        f"({mode_label.get(group_by, group_by)})"
    )

    # asset_tags always shows the interactive menu (unless --chapter was given)
    if group_by == "asset_tags" and not chapter_filter:
        _run_asset_tags_interactive(
            app_name=app_name,
            override=override,
            dry_run=dry_run,
            show_prompt=show_prompt,
            verbose=verbose,
            interactive=interactive,
            streaming=streaming,
            include_auditor_diary=include_auditor_diary,
            usage_calls=usage_calls,
        )
        return

    try:
        worklist = build_grouped_worklist(
            mode=group_by,
            app_name=app_name,
            component_filter=component_filter,
            chapter_filter=chapter_filter,
            override=override,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[bold red]✗ {exc}[/bold red]")
        raise SystemExit(1)

    if not worklist:
        console.print("[green]✓ Nothing to do — all analyses already exist.[/green]")
        return

    console.print(f"[dim]{len(worklist)} job(s) to run[/dim]")

    common_kwargs = dict(
        dry_run=dry_run,
        show_prompt=show_prompt,
        verbose=verbose,
        interactive=interactive,
        streaming=streaming,
        include_auditor_diary=include_auditor_diary,
    )

    if group_by in ("asvs_chapter", "asset_tags"):
        for asvs_key, components in worklist:
            results = run_grouped_by_chapter_job(app_name, asvs_key, components, **common_kwargs)
            usage_calls.extend(r for r in results if r.get("usage"))
    else:  # component
        for component_id, asvs_keys in worklist:
            results = run_grouped_by_component_job(app_name, component_id, asvs_keys, **common_kwargs)
            usage_calls.extend(r for r in results if r.get("usage"))


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
@click.option(
    "--group-by", "group_by",
    type=click.Choice(["asset_tags", "asvs_chapter", "component"], case_sensitive=False),
    default=None,
    help=(
        "Group multiple (component × chapter) pairs into fewer LLM calls.\n"
        "  asvs_chapter — one call per chapter (all applicable components grouped).\n"
        "  asset_tags   — interactive menu: pick tag → chapter → run pending components.\n"
        "  component    — one call per component (all applicable chapters grouped)."
    ),
)
@click.option(
    "--override", is_flag=True, default=False,
    help="Re-run analyses that already exist (also shows completed items in the menus).",
)
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
    group_by: str | None,
    override: bool,
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
            "group_by": group_by,
            "override": override,
            "dry_run": dry_run,
            "show_prompt": show_prompt,
            "verbose": verbose,
            "interactive": interactive,
            "streaming": streaming,
            "include_auditor_diary": include_auditor_diary,
        },
    )
    init_llm_session(app_name=app_name, command_name="audit")
    console.print(f"[bold cyan]🔒 Security Audit[/bold cyan] {app_name}")
    usage_calls: list[dict] = []

    # ── Grouped mode: bypass interactive menu, delegate to grouped runners ────
    if group_by:
        _run_grouped_audit(
            app_name=app_name,
            group_by=group_by,
            component_filter=component_filter,
            chapter_filter=chapter_filter,
            override=override,
            dry_run=dry_run,
            show_prompt=show_prompt,
            verbose=verbose,
            interactive=interactive,
            streaming=streaming,
            include_auditor_diary=include_auditor_diary,
            usage_calls=usage_calls,
        )
        _write_audit_usage_report(app_name, usage_calls)
        finalize_llm_session()
        return

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
        finalize_llm_session()
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
                finalize_llm_session()
                
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

    if dry_run or show_prompt:
        chars = len(prompt)
        tokens_est = chars // 4
        console.print(f"[dim]chars={chars:,}  tokens≈{tokens_est:,}[/dim]")

        if show_prompt:
            sys.stdout.write(prompt)
            sys.stdout.write("\n")
            sys.stdout.flush()
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
