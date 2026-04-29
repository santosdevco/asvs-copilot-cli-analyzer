"""
commands/batch_audit.py  —  Batch chapter audit
────────────────────────────────────────────────
Runs all pending (or all, with --override) analyses for a given ASVS chapter
across every component of an app.

Usage:
  python cli.py batch-audit <app_name> --chapter V6
    python cli.py batch-audit <app_name>
    python cli.py batch-audit <app_name> --component auth_and_session_module
    python cli.py batch-audit <app_name> --max-jobs 10
  python cli.py batch-audit <app_name> --chapter V6 --override
  python cli.py batch-audit <app_name> --chapter V6 --parallel
  python cli.py batch-audit <app_name> --chapter V6 --override --parallel --workers 4
  python cli.py batch-audit <app_name> --chapter V6 --dry-run
"""
from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from cli.config import AUDIT_PROMPT_FILE, OUTPUTS_DIR
from cli.core import (
    build_audit_context,
    complete,
    complete_interactive,
    get_applicable_asvs_keys,
    get_last_usage_summary,
    get_provider_and_model,
    load_component_index,
    missing_keys,
    render,
    write_usage_report,
    append_context_notes,
)
from cli.core.grouped_audit import (
    build_grouped_worklist,
    run_grouped_by_chapter_job,
    run_grouped_by_component_job,
)
from cli.models import ComponentItem
from cli.core.app_logger import init_app_logger, log_event, log_prompt

console = Console()


# ── per-component lock for context.md appends in parallel mode ───────────────
_context_locks: dict[str, threading.Lock] = {}
_context_locks_mutex = threading.Lock()


def _get_context_lock(component_id: str) -> threading.Lock:
    with _context_locks_mutex:
        if component_id not in _context_locks:
            _context_locks[component_id] = threading.Lock()
        return _context_locks[component_id]


# ── helpers ───────────────────────────────────────────────────────────────────

def _analysis_exists(app_name: str, component_id: str, chapter_id: str) -> bool:
    path = OUTPUTS_DIR / app_name / "components" / component_id / "analysis" / f"{chapter_id}.json"
    return path.exists()


def _chapter_id(asvs_key: str) -> str:
    return asvs_key.split("_")[0]


def _build_work_list(
    app_name: str,
    chapter_filter: str | None,
    component_filter: str | None,
    override: bool,
) -> list[tuple[ComponentItem, str]]:
    """Return (component, asvs_key) pairs that need to be audited."""
    index = load_component_index(app_name)
    selected_components = index.project_triage
    if component_filter:
        selected_components = [
            c for c in index.project_triage
            if c.component_id == component_filter
        ]
        if not selected_components:
            raise ValueError(
                f"Component '{component_filter}' not found. "
                f"Available: {[c.component_id for c in index.project_triage]}"
            )

    work: list[tuple[ComponentItem, str]] = []

    for component in selected_components:
        applicable = get_applicable_asvs_keys(component.asset_tags)
        # Optional filter by requested chapter (exact match on V-prefix)
        if chapter_filter:
            matching = [
                k for k in applicable
                if _chapter_id(k) == chapter_filter
            ]
        else:
            matching = applicable

        for asvs_key in matching:
            ch = _chapter_id(asvs_key)
            if override or not _analysis_exists(app_name, component.component_id, ch):
                work.append((component, asvs_key))

    return work


def _run_one(
    app_name: str,
    component: ComponentItem,
    asvs_key: str,
    dry_run: bool,
    include_auditor_diary: bool,
    use_lock: bool = False,
    streaming: bool = False,
) -> dict:
    """Execute a single audit call; returns a usage/result dict.

    Streaming is only effective in sequential (non-parallel) mode.
    """
    ch = _chapter_id(asvs_key)
    label = f"{component.component_id} → {ch}"

    try:
        ctx = build_audit_context(
            app_name,
            component.component_id,
            asvs_key,
            include_auditor_diary=include_auditor_diary,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]  ⚠ Skipped {label} — {exc}[/red]")
        log_event("batch_audit.skipped", {"label": label, "reason": str(exc)})
        return {"operation": "skipped", "component_id": component.component_id, "asvs_key": asvs_key}

    template = AUDIT_PROMPT_FILE.read_text(encoding="utf-8")
    absent = missing_keys(template, ctx)
    if absent:
        console.print(f"[yellow]  ⚠ Unresolved placeholders for {label}: {absent}[/yellow]")

    prompt = render(template, ctx)
    log_prompt(prompt, label=f"batch_audit_{component.component_id}_{ch}")
    log_event("batch_audit.call_started", {
        "component_id": component.component_id,
        "asvs_key": asvs_key,
        "dry_run": dry_run,
    })

    if dry_run:
        console.print(f"  [dim][dry-run] {label}  chars={len(prompt):,}  tokens≈{len(prompt)//4:,}[/dim]")
        return {"operation": "dry_run", "component_id": component.component_id, "asvs_key": asvs_key}

    console.print(f"  [cyan]→ auditing {label}…[/cyan]")
    try:
        if streaming and not use_lock:  # streaming only in sequential mode
            parsed_result, response = complete_interactive(
                prompt,
                verbose=False,
                interactive=False,
                streaming=True,
                context=f"ASVS {_chapter_id(asvs_key)} audit for {component.component_id}",
            )
        else:
            response = complete(prompt)
        usage_summary = get_last_usage_summary()
        log_event("batch_audit.call_completed", {
            "component_id": component.component_id,
            "asvs_key": asvs_key,
            "response_chars": len(response),
        })
        console.print(f"  [green]✓ {label}[/green]")

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
        log_event("batch_audit.call_failed", {
            "component_id": component.component_id,
            "asvs_key": asvs_key,
            "error": str(exc),
        })
        console.print(f"  [bold red]✗ {label} — {exc}[/bold red]")
        return {
            "operation": "audit_failed",
            "component_id": component.component_id,
            "asvs_key": asvs_key,
            "error": str(exc),
            "usage": usage_summary,
        }


def _print_plan(work: list[tuple[ComponentItem, str]], override: bool) -> None:
    table = Table(title="Batch audit plan", show_header=True, header_style="bold magenta")
    table.add_column("#", style="cyan", width=3)
    table.add_column("Component")
    table.add_column("Chapter")
    table.add_column("Risk", justify="center")

    risk_colors = {"CRITICAL": "red", "HIGH": "yellow", "MEDIUM": "blue", "LOW": "green"}
    for i, (comp, asvs_key) in enumerate(work, 1):
        ch = _chapter_id(asvs_key)
        color = risk_colors.get(comp.risk_level, "white")
        table.add_row(
            str(i),
            comp.component_id,
            ch,
            f"[{color}]{comp.risk_level}[/{color}]",
        )
    console.print(table)
    if override:
        console.print("[yellow]--override active: existing analyses will be rewritten.[/yellow]")


def _run_grouped_batch(
    app_name: str,
    group_by: str,
    component_filter: str | None,
    chapter_filter: str | None,
    override: bool,
    parallel: bool,
    workers: int,
    max_jobs: int | None,
    dry_run: bool,
    show_prompt: bool,
    streaming: bool,
    include_auditor_diary: bool,
) -> None:
    """Execute batch-audit in grouped mode and print a usage summary."""
    mode_label = {"asvs_chapter": "per chapter", "asset_tags": "per tag × chapter", "component": "per component"}
    console.print(
        f"[bold cyan]Group-by:[/bold cyan] [yellow]{group_by}[/yellow] "
        f"({mode_label.get(group_by, group_by)})"
    )

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

    if max_jobs is not None and len(worklist) > max_jobs:
        console.print(
            f"[yellow]Applying --max-jobs={max_jobs}: executing {max_jobs} of {len(worklist)} jobs.[/yellow]"
        )
        worklist = worklist[:max_jobs]

    # Print plan table
    _print_grouped_plan(worklist, group_by)

    if dry_run:
        console.print("\n[dim]Dry-run mode — no LLM calls will be made.[/dim]")

    common_kwargs = dict(
        dry_run=dry_run,
        show_prompt=show_prompt,
        verbose=False,
        interactive=False,
        streaming=streaming,
        include_auditor_diary=include_auditor_diary,
    )

    usage_calls: list[dict] = []
    if parallel and not dry_run and not show_prompt:
        console.print(f"\n[bold]Running {len(worklist)} grouped jobs in parallel (workers={workers})…[/bold]")
        futures = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            if group_by in ("asvs_chapter", "asset_tags"):
                for asvs_key, components in worklist:
                    future = pool.submit(run_grouped_by_chapter_job, app_name, asvs_key, components, **common_kwargs)
                    futures[future] = (group_by, asvs_key)
            else:
                for component_id, asvs_keys in worklist:
                    future = pool.submit(run_grouped_by_component_job, app_name, component_id, asvs_keys, **common_kwargs)
                    futures[future] = (group_by, component_id)

            for future in as_completed(futures):
                _, job_id = futures[future]
                try:
                    results = future.result()
                    usage_calls.extend(r for r in results if r.get("usage"))
                except Exception as exc:
                    console.print(f"[bold red]✗ grouped job {job_id} raised: {exc}[/bold red]")
                    # Print missing files and rerun command for failed grouped jobs
                    if hasattr(exc, 'expected_files'):
                        missing_files = [f for f in exc.expected_files if not os.path.exists(f)]
                        if missing_files:
                            console.print("[bold yellow]Missing expected files:[/bold yellow]")
                            for f in missing_files:
                                console.print(f"  [red]- {f}[/red]")
                    rerun_cmd = f"python cli.py batch-audit {app_name} --group-by {group_by} --chapter {job_id} --streaming --override"
                    console.print(f"[bold cyan]To rerun this job in isolation:[/bold cyan]\n  {rerun_cmd}")
    elif group_by in ("asvs_chapter", "asset_tags"):
        for asvs_key, components in worklist:
            results = run_grouped_by_chapter_job(app_name, asvs_key, components, **common_kwargs)
            usage_calls.extend(r for r in results if r.get("usage"))
    else:  # component
        for component_id, asvs_keys in worklist:
            results = run_grouped_by_component_job(app_name, component_id, asvs_keys, **common_kwargs)
            usage_calls.extend(r for r in results if r.get("usage"))

    if usage_calls:
        provider, model = get_provider_and_model()
        usage_path = write_usage_report(
            app_name=app_name,
            command_name="batch-audit-grouped",
            calls=usage_calls,
            provider=provider,
            model=model,
            metadata={"group_by": group_by, "jobs": len(worklist)},
        )
        total_tokens = sum(float((c.get("usage") or {}).get("total_tokens") or 0) for c in usage_calls)
        console.print(
            f"\n[cyan]📊 Usage saved → {usage_path}  "
            f"(jobs={len(worklist)} files_written={len(usage_calls)} total_tokens={total_tokens:.0f})[/cyan]"
        )

    console.print(f"\n[bold green]batch-audit (grouped) done[/bold green]  jobs={len(worklist)}")


def _print_grouped_plan(worklist: list[tuple], group_by: str) -> None:
    """Print a plan table for grouped mode."""
    table = Table(title=f"Grouped batch-audit plan (--group-by {group_by})",
                  show_header=True, header_style="bold magenta")
    table.add_column("#", style="cyan", width=3)

    if group_by in ("asvs_chapter", "asset_tags"):
        table.add_column("Chapter")
        table.add_column("Components", justify="right")
        table.add_column("Component IDs", style="dim")
        for i, (asvs_key, comps) in enumerate(worklist, 1):
            ch = asvs_key.split("_")[0]
            ids = ", ".join(c.component_id for c in comps[:3])
            if len(comps) > 3:
                ids += f" +{len(comps) - 3} more"
            table.add_row(str(i), ch, str(len(comps)), ids)
    else:  # component
        table.add_column("Component")
        table.add_column("Chapters", justify="right")
        table.add_column("Chapter IDs", style="dim")
        for i, (component_id, asvs_keys) in enumerate(worklist, 1):
            ch_ids = ", ".join(k.split("_")[0] for k in asvs_keys)
            table.add_row(str(i), component_id, str(len(asvs_keys)), ch_ids)

    console.print(table)


# ── command ───────────────────────────────────────────────────────────────────

@click.command("batch-audit")
@click.argument("app_name")
@click.option(
    "--component", "component_filter", default=None,
    help="Audit a single component ID (optional).",
)
@click.option(
    "--chapter", "chapter_filter", default=None,
    help="ASVS chapter to audit (e.g. V6). If omitted, all applicable chapters are audited.",
)
@click.option(
    "--group-by", "group_by",
    type=click.Choice(["asset_tags", "asvs_chapter", "component"], case_sensitive=False),
    default=None,
    help=(
        "Group multiple (component × chapter) pairs into fewer LLM calls.\n"
        "  asvs_chapter — one call per chapter (all applicable components grouped).\n"
        "  asset_tags   — one call per (tag × chapter) sub-group.\n"
        "  component    — one call per component (all applicable chapters grouped)."
    ),
)
@click.option(
    "--override", is_flag=True, default=False,
    help="Re-run and overwrite analyses that already exist.",
)
@click.option(
    "--parallel", is_flag=True, default=False,
    help="Run audits concurrently (default: sequential).",
)
@click.option(
    "--workers", default=3, show_default=True,
    help="Max concurrent workers when --parallel is set.",
)
@click.option(
    "--max-jobs", type=click.IntRange(min=1), default=None,
    help="Maximum number of analyses to execute in this run.",
)
@click.option(
    "--streaming", "-s", is_flag=True, default=False,
    help="Stream LLM output in real-time (sequential mode only).",
)
@click.option("--dry-run", is_flag=True, help="Show plan and rendered prompts without calling the LLM.")
@click.option("--show-prompt", is_flag=True, help="Show full prompt content in dry-run mode (grouped only).")
@click.option(
    "--include-auditor-diary/--no-include-auditor-diary",
    default=True, show_default=True,
    help="Include the AUDITOR DIARY section from context.md in the prompt.",
)
def batch_audit_cmd(
    app_name: str,
    component_filter: str | None,
    chapter_filter: str | None,
    group_by: str | None,
    override: bool,
    parallel: bool,
    workers: int,
    max_jobs: int | None,
    streaming: bool,
    dry_run: bool,
    show_prompt: bool,
    include_auditor_diary: bool,
) -> None:
    """Batch-audit all components for a single ASVS chapter.

    Skips already-completed analyses unless --override is given.
    Use --parallel to run multiple components concurrently.
    Use --group-by to consolidate calls and reduce LLM cost.
    """
    # normalise: accept "v6" or "V6"
    if chapter_filter:
        chapter_filter = chapter_filter.upper()

    if streaming and parallel:
        console.print("[yellow]⚠ --streaming is ignored in --parallel mode.[/yellow]")
        streaming = False

    init_app_logger(
        app_name=app_name,
        command_name="batch-audit",
        command_line=" ".join(sys.argv),
        options={
            "component": component_filter,
            "chapter": chapter_filter,
            "group_by": group_by,
            "override": override,
            "parallel": parallel,
            "workers": workers,
            "max_jobs": max_jobs,
            "streaming": streaming,
            "dry_run": dry_run,
            "include_auditor_diary": include_auditor_diary,
        },
    )

    console.print(
        f"[bold cyan]batch-audit[/bold cyan] {app_name}  "
        f"component=[bold]{component_filter or 'ALL'}[/bold]  "
        f"chapter=[bold]{chapter_filter or 'ALL'}[/bold]  "
        f"group-by=[bold]{group_by or 'none'}[/bold]  "
        f"override={override}  parallel={parallel}"
    )

    # ── Grouped mode ──────────────────────────────────────────────────────────
    if group_by:
        _run_grouped_batch(
            app_name=app_name,
            group_by=group_by,
            component_filter=component_filter,
            chapter_filter=chapter_filter,
            override=override,
            parallel=parallel,
            workers=workers,
            max_jobs=max_jobs,
            dry_run=dry_run,
            show_prompt=show_prompt,
            streaming=streaming,
            include_auditor_diary=include_auditor_diary,
        )
        return

    # ── Build work list ───────────────────────────────────────────────────────
    try:
        work = _build_work_list(app_name, chapter_filter, component_filter, override)
    except FileNotFoundError as exc:
        console.print(f"[bold red]✗ {exc}[/bold red]")
        raise SystemExit(1)
    except ValueError as exc:
        console.print(f"[bold red]✗ {exc}[/bold red]")
        raise SystemExit(1)

    if not work:
        chapter_scope = chapter_filter or "all chapters"
        component_scope = component_filter or "all components"
        console.print(
            f"[green]✓ Nothing to do for {component_scope} / {chapter_scope}.[/green]\n"
            "  Use [bold]--override[/bold] to force re-run."
        )
        return

    if max_jobs is not None and len(work) > max_jobs:
        total_pending = len(work)
        work = work[:max_jobs]
        console.print(
            f"[yellow]Applying --max-jobs={max_jobs}: executing {len(work)} of {total_pending} pending analyses.[/yellow]"
        )

    _print_plan(work, override)
    log_event("batch_audit.plan", {
        "component": component_filter,
        "chapter": chapter_filter,
        "total_jobs": len(work),
        "max_jobs": max_jobs,
        "override": override,
        "parallel": parallel,
    })

    if dry_run:
        console.print("\n[dim]Dry-run mode — no LLM calls will be made.[/dim]")

    # ── Execute ───────────────────────────────────────────────────────────────
    usage_calls: list[dict] = []

    if parallel and not dry_run:
        console.print(f"\n[bold]Running {len(work)} audits in parallel (workers={workers})…[/bold]")
        futures = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for comp, asvs_key in work:
                f = pool.submit(
                    _run_one,
                    app_name, comp, asvs_key, dry_run, include_auditor_diary,
                    True,   # use_lock=True for parallel writes
                )
                futures[f] = (comp.component_id, _chapter_id(asvs_key))

        for f in as_completed(futures):
            comp_id, ch = futures[f]
            try:
                result = f.result()
                if result.get("usage"):
                    usage_calls.append(result)
            except Exception as exc:
                console.print(f"[bold red]✗ {comp_id} → {ch} raised: {exc}[/bold red]")
    else:
        if dry_run:
            console.print(f"\n[dim]Plan ({len(work)} jobs):[/dim]")
        else:
            console.print(f"\n[bold]Running {len(work)} audits sequentially…[/bold]")

        for comp, asvs_key in work:
            result = _run_one(
                app_name, comp, asvs_key, dry_run, include_auditor_diary,
                use_lock=False, streaming=streaming,
            )
            if result.get("usage"):
                usage_calls.append(result)

    # ── Usage report ──────────────────────────────────────────────────────────
    if usage_calls:
        provider, model = get_provider_and_model()
        usage_path = write_usage_report(
            app_name=app_name,
            command_name="audit",   # keeps *_audit_usage.json naming convention
            calls=usage_calls,
            provider=provider,
            model=model,
            metadata={
                "component": component_filter,
                "chapter": chapter_filter,
                "jobs": len(work),
                "max_jobs": max_jobs,
                "parallel": parallel,
            },
        )
        total_tokens = sum(float((c.get("usage") or {}).get("total_tokens") or 0) for c in usage_calls)
        console.print(
            f"\n[cyan]📊 Usage saved → {usage_path}  "
            f"(calls={len(usage_calls)} total_tokens={total_tokens:.0f})[/cyan]"
        )

    completed = sum(1 for c in usage_calls if c.get("operation") == "audit")
    failed = sum(1 for c in usage_calls if "failed" in (c.get("operation") or ""))
    skipped = len(work) - completed - failed

    console.print(
        f"\n[bold green]batch-audit done[/bold green]  "
        f"completed={completed}  failed={failed}  skipped={skipped}"
    )
    log_event("batch_audit.done", {
        "component": component_filter,
        "chapter": chapter_filter,
        "max_jobs": max_jobs,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
    })
