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
import pyperclip
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from rich.table import Table

from cli.config import AUDIT_PROMPT_FILE, ANALYSIS_OUTPUT_FORMAT
from cli.core import (
    build_audit_context,
    complete,
    complete_interactive,
    get_provider_and_model,
    get_applicable_asvs_keys,
    get_recommended_and_unrecommended_chapters,
    load_component_index,
    missing_keys,
    render,
    write_usage_report,
)
from cli.core import init_llm_session, finalize_llm_session
from rich.prompt import Prompt as RichPrompt


# Valid prompt sections
VALID_PROMPT_SECTIONS = {
    "component_context",
    "filtered_static_context",
    "file_contents",
    "files_to_audit",
}


def _validate_prompt_sections(ctx, param, value: str) -> str:
    """Validate and normalize prompt sections parameter.

    Raises Click.BadParameter if any section is invalid.
    """
    if not value:
        return value

    sections = set(s.strip().lower() for s in value.split(",") if s.strip())
    invalid = sections - VALID_PROMPT_SECTIONS

    if invalid:
        valid_list = ", ".join(sorted(VALID_PROMPT_SECTIONS))
        raise click.BadParameter(
            f"Invalid prompt section(s): {', '.join(sorted(invalid))}. "
            f"Valid options are: {valid_list}"
        )

    return ",".join(sorted(sections))
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
from cli.commands.save_analysis import _extract_json

# Summary/status output goes to stderr so stdout stays clean for redirection
console = Console(stderr=True)


def _write_audit_usage_report(app_name: str, usage_calls: list[dict]) -> None:
    """Persist usage report for this audit command execution."""
    console.print(f"[yellow]DEBUG: _write_audit_usage_report called with {len(usage_calls)} calls[/yellow]")

    if not usage_calls:
        console.print("[yellow]⚠ No usage calls to report[/yellow]")
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


def _save_pasted_analysis(app_name: str, component: ComponentItem, asvs_key: str) -> None:
    """Save analysis results pasted by user in dry-run mode."""
    chapter_id = asvs_key.split("_")[0]
    console.print("\n[cyan]Paste the analysis JSON result, then press Ctrl+D (Linux/Mac) or Ctrl+Z+Enter (Windows):[/cyan]")

    try:
        pasted_content = sys.stdin.read()
        if not pasted_content.strip():
            console.print("[yellow]⚠ No content pasted[/yellow]")
            return

        # Extract JSON (handles plain JSON, markdown fences, and free-form text)
        analysis_data, is_raw = _extract_json(pasted_content)
        if is_raw:
            console.print("[yellow]⚠ Could not identify a single JSON object — saving raw content as-is.[/yellow]")

        # Ensure output directory exists
        output_dir = Path(f"outputs/{app_name}/components/{component.component_id}/analysis")
        output_dir.mkdir(parents=True, exist_ok=True)

        # Remove any existing files with same chapter name but different extension
        for existing in output_dir.glob(f"{chapter_id}.*"):
            if existing.suffix.lower() in (".json", ".xml"):
                existing.unlink()

        # Save to file with normalized extension
        target_format = ANALYSIS_OUTPUT_FORMAT if ANALYSIS_OUTPUT_FORMAT in ("json", "xml") else "json"
        output_file = output_dir / f"{chapter_id}.{target_format}"
        with open(output_file, "w") as f:
            if is_raw or target_format == "xml":
                f.write(pasted_content)
            else:
                json.dump(analysis_data, f, indent=2, ensure_ascii=False)

        console.print(f"[green]✅ Saved analysis to {output_file}[/green]")
        log_event(
            "audit.pasted_analysis_saved",
            {"component_id": component.component_id, "asvs_key": asvs_key, "file": str(output_file)},
        )

    except KeyboardInterrupt:
        console.print("[yellow]⚠ Cancelled[/yellow]")


def _scan_existing_analyses(app_name: str) -> dict[str, dict[str, dict]]:
    """Scan for existing analysis files and return progress data."""
    analyses = {}
    components_dir = Path(f"outputs/{app_name}/components")

    if not components_dir.exists():
        return {}

    target_format = ANALYSIS_OUTPUT_FORMAT if ANALYSIS_OUTPUT_FORMAT in ("json", "xml") else "json"

    for component_dir in components_dir.iterdir():
        if not component_dir.is_dir() or component_dir.name in ['README.md', 'index.json']:
            continue

        component_id = component_dir.name
        analyses[component_id] = {}

        analysis_dir = component_dir / "analysis"
        if analysis_dir.exists():
            # Case-insensitive extension matching
            for analysis_file in analysis_dir.iterdir():
                if not analysis_file.is_file():
                    continue

                file_ext = analysis_file.suffix.lower()
                if file_ext != f".{target_format}":
                    continue

                chapter = analysis_file.stem  # V1, V2, etc.
                try:
                    if target_format == "xml":
                        import xml.etree.ElementTree as ET
                        root = ET.parse(analysis_file).getroot()
                        reqs = root.findall("requirements/requirement")
                        issues = sum(1 for r in reqs if r.get("status") == "FAIL")
                    else:  # json
                        data = json.load(analysis_file.open())
                        reqs = data.get("results", [])
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
    table.add_column("Folder ID", style="dim")
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
            component.component_id,
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


def _select_chapter_interactive(
    component: ComponentItem,
    analyses: dict,
    include_unrecommended: bool = True,
    only_unrecommended: bool = False,
) -> str | None:
    """Show chapter selection menu for a component.

    Args:
        component: Component to audit
        analyses: Existing analyses dict
        include_unrecommended: If True, show unrecommended chapters; if False, only show recommended.
        only_unrecommended: If True, show ONLY unrecommended chapters (overrides include_unrecommended).
    """
    component_analyses = analyses.get(component.component_id, {})

    console.print(f"\n[bold cyan]📖 ASVS Chapters for {component.component_name}:[/bold cyan]")

    # Get recommended and unrecommended chapters
    recommended, unrecommended = get_recommended_and_unrecommended_chapters(component.asset_tags)

    # Decide which chapters to show based on scope
    if only_unrecommended:
        # Only show unrecommended chapters
        shown_recommended = []
        shown_unrecommended = unrecommended
    elif include_unrecommended:
        # Show both
        shown_recommended = recommended
        shown_unrecommended = unrecommended
    else:
        # Show only recommended
        shown_recommended = recommended
        shown_unrecommended = []

    # Create table with chapter info
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", style="cyan", width=3)
    table.add_column("Chapter", style="bold")
    table.add_column("Title", style="dim")
    table.add_column("Recommended", justify="center", width=12)
    table.add_column("Status", justify="center")

    chapter_map = {}
    counter = 1

    # Add recommended chapters
    for asvs_key in shown_recommended:
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
            str(counter),
            chapter_id,
            chapter_title[:40],
            "[green]✓[/green]",
            status
        )
        chapter_map[str(counter)] = asvs_key
        counter += 1

    # Add unrecommended chapters (if enabled)
    for asvs_key in shown_unrecommended:
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
            str(counter),
            chapter_id,
            chapter_title[:40],
            "[dim]⊘[/dim]",
            status
        )
        chapter_map[str(counter)] = asvs_key
        counter += 1

    console.print(table)

    # Find first pending chapter
    first_pending = None
    for idx, asvs_key in enumerate(shown_recommended + shown_unrecommended, 1):
        chapter_id = asvs_key.split("_")[0]
        if chapter_id not in component_analyses:
            first_pending = str(idx)
            break

    # Get selection
    help_text = "\nEnter chapter number (or 'b' for back, 'n' for next pending, 'q' to quit)"
    choices = list(chapter_map.keys()) + ['b', 'n', 'q']
    choice = Prompt.ask(help_text, choices=choices)
    log_event(
        "audit.chapter_choice",
        {"component_id": component.component_id, "choice": choice},
    )

    if choice == 'n':
        if first_pending:
            return chapter_map[first_pending]
        else:
            console.print("[green]✓ All chapters analyzed[/green]")
            return _select_chapter_interactive(component, analyses, include_unrecommended, only_unrecommended)

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
    prompt_sections: str,
    copy_clipboard: bool,
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
        prompt_sections=prompt_sections,
        copy_clipboard=copy_clipboard,
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

            # DEBUG: Check what we got
            console.print(f"[yellow]DEBUG: Got {len(results)} results from grouped job[/yellow]")
            for i, r in enumerate(results):
                has_usage = r.get("usage")
                console.print(f"[yellow]  Result {i}: usage={'present' if has_usage else 'missing/empty'}, keys={list(r.keys())}[/yellow]")
                if has_usage:
                    console.print(f"[yellow]    usage content: {r.get('usage')}[/yellow]")

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

    # After interactive loop ends
    console.print(f"[yellow]DEBUG: Exiting asset_tags interactive mode with {len(usage_calls)} usage calls[/yellow]")


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
    prompt_sections: str,
    copy_clipboard: bool,
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
            prompt_sections=prompt_sections,
            copy_clipboard=copy_clipboard,
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
        prompt_sections=prompt_sections,
        copy_clipboard=copy_clipboard,
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
@click.option(
    "--active-tools",
    default=None,
    help=(
        "Comma-separated list of tools to enable for Claude SDK (e.g., 'Read,Write,Edit'). "
        "Use 'None' to disable all tools. Only applies when LLM_PROVIDER=claude."
    ),
)
@click.option(
    "--prompt-sections",
    type=str,
    default="component_context,filtered_static_context,file_contents,files_to_audit",
    callback=_validate_prompt_sections,
    help=(
        "Comma-separated list of prompt sections to include. "
        "Options: component_context, filtered_static_context, file_contents, files_to_audit. "
        "Default includes all."
    ),
)
@click.option(
    "--copy-clipboard",
    is_flag=True,
    default=False,
    help="Automatically copy the prompt to the clipboard (useful with --show-prompt).",
)
@click.option(
    "--it",
    "interactive_mode",
    default=True,
    type=bool,
    show_default=True,
    help="Interactive mode; set false to skip prompts (e.g. --it false).",
)
@click.option(
    "--chapter-scope",
    type=click.Choice(["all", "recommended-only", "unrecommended-only"], case_sensitive=False),
    default="all",
    help=(
        "Filter chapters by recommendation status:\n"
        "  all — show all chapters (default)\n"
        "  recommended-only — only show chapters recommended for component\n"
        "  unrecommended-only — only show chapters NOT recommended for component"
    ),
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
    active_tools: str | None,
    prompt_sections: str,
    copy_clipboard: bool,
    interactive_mode: bool,
    chapter_scope: str,
) -> None:
    """Step 4 — Interactive security audit with progress tracking."""

    # Convert chapter_scope to include/exclude unrecommended
    # "all" → include unrecommended (True)
    # "recommended-only" → exclude unrecommended (False)
    # "unrecommended-only" → only unrecommended (special handling)
    include_unrecommended = chapter_scope.lower() != "recommended-only"
    only_unrecommended = chapter_scope.lower() == "unrecommended-only"

    # Parse active_tools flag
    parsed_tools: list[str] | None = None
    if active_tools is not None:
        if active_tools.strip().lower() == "none":
            parsed_tools = []
        else:
            parsed_tools = [t.strip() for t in active_tools.split(",") if t.strip()]

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
            "active_tools": active_tools,
            "prompt_sections": prompt_sections,
        },
    )
    init_llm_session(app_name=app_name, command_name="audit", active_tools=parsed_tools)
    console.print(f"[bold cyan]🔒 Security Audit[/bold cyan] {app_name}")

    if active_tools is not None:
        tools_display = "none" if not parsed_tools else ", ".join(parsed_tools)
        console.print(f"[dim]Active tools: {tools_display}[/dim]")
    if "file_contents" in prompt_sections:
        console.print("[dim]Prompt sections: file contents enabled (increased token usage)[/dim]")

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
            prompt_sections=prompt_sections,
            copy_clipboard=copy_clipboard,
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
        recommended, unrecommended = get_recommended_and_unrecommended_chapters(selected_component.asset_tags)

        # Determine which chapters to consider based on scope
        if only_unrecommended:
            chapters_to_consider = unrecommended
        elif not include_unrecommended:
            chapters_to_consider = recommended
        else:
            chapters_to_consider = recommended + unrecommended

        # Handle --chapter n (next pending)
        if chapter_filter == 'n':
            component_analyses = analyses.get(selected_component.component_id, {})
            pending = [k for k in chapters_to_consider if k.split('_')[0] not in component_analyses]
            if not pending:
                scope_label = {
                    True: "unrecommended",
                    False: "recommended"
                }.get(only_unrecommended, "")
                if scope_label:
                    console.print(f"[green]✓ All {scope_label} chapters already analyzed for {component_filter}[/green]")
                else:
                    console.print(f"[green]✓ All chapters already analyzed for {component_filter}[/green]")
                finalize_llm_session()
                return
            matching_chapters = [pending[0]]
        else:
            # Find matching chapter
            matching_chapters = [k for k in chapters_to_consider if k.startswith(chapter_filter)]
            if not matching_chapters:
                scope_label = {
                    True: "unrecommended for",
                    False: "recommended for"
                }.get(only_unrecommended, "applicable to")
                console.print(f"[bold red]Chapter {chapter_filter} not {scope_label} {component_filter}[/bold red]")
                finalize_llm_session()
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
            prompt_sections,
            copy_clipboard,
            interactive_mode,
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
            result = _select_chapter_interactive(selected_component, analyses, include_unrecommended, only_unrecommended)
            
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
                    prompt_sections,
                    copy_clipboard,
                    interactive_mode,
                )
                if call_usage:
                    usage_calls.append(call_usage)
                    _print_call_usage(call_usage)
                    _write_audit_usage_report(app_name, usage_calls)
                finalize_llm_session()
                
                # Refresh analyses after audit
                analyses = _scan_existing_analyses(app_name)

                if not interactive_mode or not Confirm.ask("\nRun another audit?"):
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
    prompt_sections: str = "component_context,filtered_static_context,file_contents,files_to_audit",
    copy_clipboard: bool = False,
    interactive_mode: bool = True,
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
            prompt_sections=prompt_sections,
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

        if not interactive_mode:
            # Batch/script mode: raw prompt to stdout only, nothing else
            sys.stdout.write(prompt)
            sys.stdout.write("\n")
            sys.stdout.flush()
        else:
            # Interactive mode: clipboard + stats + optional show-prompt
            if copy_clipboard:
                try:
                    pyperclip.copy(prompt)
                    console.print("[green]✅ Prompt copied to clipboard[/green]")
                except Exception as e:
                    console.print(f"[yellow]⚠ Could not copy to clipboard: {e}[/yellow]")

            console.print(f"[dim]chars={chars:,}  tokens≈{tokens_est:,}[/dim]")
            if show_prompt:
                sys.stdout.write(prompt)
                sys.stdout.write("\n")
                sys.stdout.flush()

            if dry_run and Confirm.ask("\n[cyan]Do you want to paste analysis results to save?[/cyan]"):
                _save_pasted_analysis(app_name, component, asvs_key)

        return None

    # Call LLM
    console.print("🤖 Calling AI for security analysis...")
    usage_summary = {}
    try:
        if verbose or interactive or streaming:
            usage_summary, response = complete_interactive(
                prompt,
                verbose=verbose,
                interactive=interactive,
                streaming=streaming,
                context=f"ASVS {chapter_id} audit for {component.component_id}"
            )
        else:
            response = complete(prompt)

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
