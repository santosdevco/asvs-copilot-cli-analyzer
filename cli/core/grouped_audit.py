"""
grouped_audit.py
────────────────
Orchestration for grouped audit modes (--group-by).

Public API:
  build_grouped_worklist(mode, app_name, component_filter, chapter_filter, override)
      → list of job tuples ready for the grouped runners

  run_grouped_by_chapter_job(app_name, asvs_key, components, *, ...)
      → list[dict]  (one usage/result dict per written analysis file)

  run_grouped_by_component_job(app_name, component_id, asvs_keys, *, ...)
      → list[dict]

Both runners return the same shape as the per-call dicts in audit.py / batch_audit.py
so callers can accumulate them into usage_calls without changes.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from rich.console import Console
from rich.panel import Panel

from cli.config import (
    ASVS_ASSET_RELATION_FILE,
    ASVS_JSON_DIR,
    AUDIT_BY_CHAPTER_PROMPT_FILE,
    AUDIT_BY_COMPONENT_PROMPT_FILE,
    OUTPUTS_DIR,
)
from cli.core import (
    complete,
    complete_interactive,
    get_applicable_asvs_keys,
    get_last_usage_summary,
    load_component_index,
    missing_keys,
    render,
    write_audit_result,
)
from cli.core.context_builder import _load_json
from cli.core.grouped_context_builders import (
    build_by_chapter_context,
    build_by_component_context,
)
from cli.core.app_logger import log_event, log_prompt
from cli.models import ComponentItem
from cli.models.audit_result import GroupedAuditOutput

console = Console(stderr=True)


def _snapshot_paths(paths: list[Path]) -> dict[Path, tuple[bool, int | None]]:
    """Capture existence and mtime for later direct-write detection."""
    snapshot: dict[Path, tuple[bool, int | None]] = {}
    for path in paths:
        if path.exists():
            snapshot[path] = (True, path.stat().st_mtime_ns)
        else:
            snapshot[path] = (False, None)
    return snapshot


def _path_changed(snapshot: dict[Path, tuple[bool, int | None]], path: Path) -> bool:
    existed_before, mtime_before = snapshot.get(path, (False, None))
    if not path.exists():
        return False
    if not existed_before:
        return True
    return path.stat().st_mtime_ns != mtime_before


def _analysis_path(app_name: str, component_id: str, chapter_id: str) -> Path:
    return OUTPUTS_DIR / app_name / "components" / component_id / "analysis" / f"{chapter_id}.xml"

# ── helpers ───────────────────────────────────────────────────────────────────

def _chapter_id(asvs_key: str) -> str:
    return asvs_key.split("_")[0]


def _analysis_exists(app_name: str, component_id: str, chapter_id: str) -> bool:
    return _analysis_path(app_name, component_id, chapter_id).exists()


def _all_analyses_exist(app_name: str, components: list[ComponentItem], chapter_id: str) -> bool:
    return all(_analysis_exists(app_name, c.component_id, chapter_id) for c in components)


def _all_chapters_exist(app_name: str, component_id: str, asvs_keys: list[str]) -> bool:
    return all(_analysis_exists(app_name, component_id, _chapter_id(k)) for k in asvs_keys)


# ── worklist builders ─────────────────────────────────────────────────────────

def _filter_components(
    app_name: str,
    component_filter: str | None,
) -> list[ComponentItem]:
    index = load_component_index(app_name)
    if not component_filter:
        return index.project_triage
    matches = [c for c in index.project_triage if c.component_id == component_filter]
    if not matches:
        available = [c.component_id for c in index.project_triage]
        raise ValueError(f"Component '{component_filter}' not found. Available: {available}")
    return matches


def _normalise_chapter(chapter_filter: str | None) -> str | None:
    return chapter_filter.upper() if chapter_filter else None


def _build_by_chapter_worklist(
    app_name: str,
    component_filter: str | None,
    chapter_filter: str | None,
    override: bool,
    group_by_tag: bool,
) -> list[tuple[str, list[ComponentItem]]]:
    """Returns list of (asvs_key, [components]) jobs."""
    chapter_filter = _normalise_chapter(chapter_filter)
    components = _filter_components(app_name, component_filter)
    asvs_matrix = _load_json(ASVS_ASSET_RELATION_FILE)["asvs_routing_matrix"]

    # Collect all (asvs_key, component, primary_tag) triples
    triples: list[tuple[str, ComponentItem, str]] = []
    for comp in components:
        applicable = get_applicable_asvs_keys(comp.asset_tags)
        if chapter_filter:
            applicable = [k for k in applicable if _chapter_id(k) == chapter_filter]
        for asvs_key in applicable:
            chapter_targets = set(asvs_matrix[asvs_key].get("target_assets", []))
            primary_tag = next(
                (t for t in comp.asset_tags if t in chapter_targets),
                comp.asset_tags[0] if comp.asset_tags else "untagged",
            )
            triples.append((asvs_key, comp, primary_tag))

    # Group: by (asvs_key, tag) when group_by_tag, else by asvs_key
    groups: dict[tuple, list[ComponentItem]] = {}
    for asvs_key, comp, primary_tag in triples:
        group_key = (asvs_key, primary_tag) if group_by_tag else (asvs_key,)
        groups.setdefault(group_key, []).append(comp)

    # Build jobs, applying skip logic
    jobs: list[tuple[str, list[ComponentItem]]] = []
    for group_key, comps in groups.items():
        asvs_key = group_key[0]
        ch = _chapter_id(asvs_key)
        if not override and _all_analyses_exist(app_name, comps, ch):
            continue
        jobs.append((asvs_key, comps))

    return jobs


def _build_by_component_worklist(
    app_name: str,
    component_filter: str | None,
    chapter_filter: str | None,
    override: bool,
) -> list[tuple[str, list[str]]]:
    """Returns list of (component_id, [asvs_keys]) jobs."""
    chapter_filter = _normalise_chapter(chapter_filter)
    components = _filter_components(app_name, component_filter)

    jobs: list[tuple[str, list[str]]] = []
    for comp in components:
        applicable = get_applicable_asvs_keys(comp.asset_tags)
        if chapter_filter:
            applicable = [k for k in applicable if _chapter_id(k) == chapter_filter]
        if not applicable:
            continue
        if not override and _all_chapters_exist(app_name, comp.component_id, applicable):
            continue
        jobs.append((comp.component_id, applicable))

    return jobs


def build_grouped_worklist(
    mode: str,
    app_name: str,
    component_filter: str | None = None,
    chapter_filter: str | None = None,
    override: bool = False,
) -> list[tuple]:
    """Return a list of job tuples for the requested group-by mode.

    asvs_chapter / asset_tags → list of (asvs_key, [ComponentItem])
    component                 → list of (component_id, [asvs_key])
    """
    if mode == "asvs_chapter":
        return _build_by_chapter_worklist(
            app_name, component_filter, chapter_filter, override, group_by_tag=False
        )
    if mode == "asset_tags":
        return _build_by_chapter_worklist(
            app_name, component_filter, chapter_filter, override, group_by_tag=True
        )
    if mode == "component":
        return _build_by_component_worklist(
            app_name, component_filter, chapter_filter, override
        )
    raise ValueError(f"Unknown group-by mode: '{mode}'. Expected: asvs_chapter, asset_tags, component")


# ── asset_tags interactive menu data ─────────────────────────────────────────

class TagStats:
    """Progress data for one asset tag shown in the interactive menu."""

    def __init__(self, tag: str) -> None:
        self.tag = tag
        # chapter_id → {total: int, completed: int}
        self.chapters: dict[str, dict] = {}

    def add(self, chapter_id: str, component_id: str, done: bool) -> None:
        entry = self.chapters.setdefault(chapter_id, {"total": 0, "completed": 0})
        entry["total"] += 1
        if done:
            entry["completed"] += 1

    @property
    def total_pairs(self) -> int:
        return sum(v["total"] for v in self.chapters.values())

    @property
    def completed_pairs(self) -> int:
        return sum(v["completed"] for v in self.chapters.values())

    @property
    def pending_chapters(self) -> list[str]:
        """Chapter IDs that still have at least one pending component."""
        return [ch for ch, v in self.chapters.items() if v["completed"] < v["total"]]


def get_tag_chapter_stats(
    app_name: str,
    override: bool = False,
) -> dict[str, TagStats]:
    """Return a {tag: TagStats} mapping for every tag in the index.

    When *override* is True every (component, chapter) is counted as pending.
    """
    asvs_matrix = _load_json(ASVS_ASSET_RELATION_FILE)["asvs_routing_matrix"]
    components = _filter_components(app_name, None)
    stats: dict[str, TagStats] = {}

    for comp in components:
        applicable = get_applicable_asvs_keys(comp.asset_tags)
        for asvs_key in applicable:
            ch = _chapter_id(asvs_key)
            chapter_targets = set(asvs_matrix[asvs_key].get("target_assets", []))
            primary_tag = next(
                (t for t in comp.asset_tags if t in chapter_targets),
                comp.asset_tags[0] if comp.asset_tags else "untagged",
            )
            if primary_tag not in stats:
                stats[primary_tag] = TagStats(primary_tag)
            done = (not override) and _analysis_exists(app_name, comp.component_id, ch)
            stats[primary_tag].add(ch, comp.component_id, done)

    return stats


def get_pending_components_for_tag_chapter(
    app_name: str,
    tag: str,
    asvs_key: str,
    override: bool = False,
) -> list[ComponentItem]:
    """Return the components (for a specific tag) that still need asvs_key audited."""
    asvs_matrix = _load_json(ASVS_ASSET_RELATION_FILE)["asvs_routing_matrix"]
    ch = _chapter_id(asvs_key)
    chapter_targets = set(asvs_matrix[asvs_key].get("target_assets", []))
    components = _filter_components(app_name, None)

    result: list[ComponentItem] = []
    for comp in components:
        applicable = get_applicable_asvs_keys(comp.asset_tags)
        if asvs_key not in applicable:
            continue
        primary_tag = next(
            (t for t in comp.asset_tags if t in chapter_targets),
            comp.asset_tags[0] if comp.asset_tags else "untagged",
        )
        if primary_tag != tag:
            continue
        if override or not _analysis_exists(app_name, comp.component_id, ch):
            result.append(comp)

    return result


def get_asvs_key_for_chapter(chapter_id: str) -> str:
    """Return the full asvs_key (e.g. 'V6_Authentication') for a chapter_id (e.g. 'V6')."""
    matrix = _load_json(ASVS_ASSET_RELATION_FILE)["asvs_routing_matrix"]
    for key in matrix:
        if key.split("_")[0] == chapter_id:
            return key
    raise KeyError(f"No ASVS key found for chapter '{chapter_id}'")


# ── job runners ───────────────────────────────────────────────────────────────

def _call_llm(
    prompt: str,
    label: str,
    verbose: bool,
    interactive: bool,
    streaming: bool,
) -> str:
    if verbose or interactive or streaming:
        _, response = complete_interactive(
            prompt,
            verbose=verbose,
            interactive=interactive,
            streaming=streaming,
            context=label,
        )
        return response
    return complete(prompt)


def run_grouped_by_chapter_job(
    app_name: str,
    asvs_key: str,
    components: List[ComponentItem],
    *,
    dry_run: bool = False,
    show_prompt: bool = False,
    verbose: bool = False,
    interactive: bool = False,
    streaming: bool = False,
    include_auditor_diary: bool = True,
) -> list[dict]:
    """Run one grouped audit: 1 ASVS chapter × N components.

    Returns a list of usage/result dicts (one per successfully written file).
    """
    ch = _chapter_id(asvs_key)
    comp_ids = [c.component_id for c in components]
    label = f"[group-chapter] {ch} × {len(components)} components"
    console.print(f"\n[bold yellow]🔍 {label}[/bold yellow]")

    try:
        ctx = build_by_chapter_context(app_name, asvs_key, components, include_auditor_diary)
    except FileNotFoundError as exc:
        console.print(f"[red]⚠ Skipped — {exc}[/red]")
        return []

    template = AUDIT_BY_CHAPTER_PROMPT_FILE.read_text(encoding="utf-8")
    absent = missing_keys(template, ctx)
    if absent:
        console.print(f"[yellow]⚠ Unresolved placeholders: {absent}[/yellow]")

    prompt = render(template, ctx)
    log_prompt(prompt, label=f"grouped_chapter_{ch}")
    log_event("grouped_audit.by_chapter.started", {"asvs_key": asvs_key, "components": comp_ids})
    expected_paths = [_analysis_path(app_name, component_id, ch) for component_id in comp_ids]
    expected_snapshot = _snapshot_paths(expected_paths)

    if dry_run or show_prompt:
        console.print(f"[dim]chars={len(prompt):,}  tokens≈{len(prompt)//4:,}[/dim]")
        if show_prompt:
            sys.stdout.write(prompt)
            sys.stdout.write("\n")
            sys.stdout.flush()
        return []

    console.print(f"🤖 Calling AI ({len(components)} components, chapter {ch})…")
    try:
        response = _call_llm(prompt, label, verbose, interactive, streaming)
        usage_summary = get_last_usage_summary()
        log_event("grouped_audit.by_chapter.completed", {
            "asvs_key": asvs_key,
            "response_chars": len(response),
        })
    except Exception as exc:
        usage_summary = get_last_usage_summary()
        log_event("grouped_audit.by_chapter.failed", {"asvs_key": asvs_key, "error": str(exc)})
        console.print(f"[bold red]❌ {label} — {exc}[/bold red]")
        return [{"operation": "grouped_audit_failed", "asvs_key": asvs_key,
                 "components": comp_ids, "error": str(exc), "usage": usage_summary}]

    changed_paths = {
        component_id: path
        for component_id, path in zip(comp_ids, expected_paths)
        if _path_changed(expected_snapshot, path)
    }

    grouped = None
    parse_error = None
    if response.strip():
        try:
            grouped = GroupedAuditOutput.parse_grouped(response)
        except Exception as exc:
            parse_error = exc

    if grouped is None and changed_paths:
        console.print(
            f"[dim]Detected direct file writes for {len(changed_paths)} component(s); skipping stdout JSON parsing.[/dim]"
        )
        results: list[dict] = []
        for cid in comp_ids:
            if cid not in changed_paths:
                console.print(f"  [yellow]⚠ {cid} → {ch} was not updated[/yellow]")
                continue
            console.print(f"  [green]✓ {cid} → {ch}[/green]")
            results.append({
                "operation": "grouped_audit",
                "component_id": cid,
                "asvs_key": asvs_key,
                "prompt_chars": len(prompt),
                "response_chars": len(response),
                "usage": usage_summary,
            })
        return results

    if grouped is None:
        error = parse_error or ValueError("LLM returned no JSON and did not update any expected analysis files")
        log_event("grouped_audit.by_chapter.failed", {"asvs_key": asvs_key, "error": str(error)})
        console.print(f"[bold red]❌ {label} — {error}[/bold red]")
        return [{"operation": "grouped_audit_failed", "asvs_key": asvs_key,
                 "components": comp_ids, "error": str(error), "usage": usage_summary}]

    # Write one analysis file per AuditOutput in the response
    results: list[dict] = []
    for audit_output in grouped.results:
        cid = audit_output.component_id
        try:
            write_audit_result(app_name, cid, asvs_key, audit_output)
            console.print(f"  [green]✓ {cid} → {ch}[/green]")
            results.append({
                "operation": "grouped_audit",
                "component_id": cid,
                "asvs_key": asvs_key,
                "prompt_chars": len(prompt),
                "response_chars": len(response),
                "usage": usage_summary,
            })
        except Exception as exc:
            console.print(f"  [red]✗ write failed for {cid}: {exc}[/red]")

    return results


def run_grouped_by_component_job(
    app_name: str,
    component_id: str,
    asvs_keys: List[str],
    *,
    dry_run: bool = False,
    show_prompt: bool = False,
    verbose: bool = False,
    interactive: bool = False,
    streaming: bool = False,
    include_auditor_diary: bool = True,
) -> list[dict]:
    """Run one grouped audit: 1 component × N ASVS chapters.

    Returns a list of usage/result dicts (one per successfully written file).
    """
    chapter_ids = [_chapter_id(k) for k in asvs_keys]
    label = f"[group-component] {component_id} × {len(asvs_keys)} chapters"
    console.print(f"\n[bold yellow]🔍 {label}[/bold yellow]")

    try:
        ctx = build_by_component_context(app_name, component_id, asvs_keys, include_auditor_diary)
    except FileNotFoundError as exc:
        console.print(f"[red]⚠ Skipped — {exc}[/red]")
        return []

    template = AUDIT_BY_COMPONENT_PROMPT_FILE.read_text(encoding="utf-8")
    absent = missing_keys(template, ctx)
    if absent:
        console.print(f"[yellow]⚠ Unresolved placeholders: {absent}[/yellow]")

    prompt = render(template, ctx)
    log_prompt(prompt, label=f"grouped_component_{component_id}")
    log_event("grouped_audit.by_component.started", {
        "component_id": component_id, "asvs_keys": asvs_keys,
    })
    expected_paths = [_analysis_path(app_name, component_id, _chapter_id(asvs_key)) for asvs_key in asvs_keys]
    expected_snapshot = _snapshot_paths(expected_paths)

    if dry_run or show_prompt:
        console.print(f"[dim]chars={len(prompt):,}  tokens≈{len(prompt)//4:,}[/dim]")
        if show_prompt:
            sys.stdout.write(prompt)
            sys.stdout.write("\n")
            sys.stdout.flush()
        return []

    console.print(f"🤖 Calling AI ({component_id}, {len(asvs_keys)} chapters)…")
    try:
        response = _call_llm(prompt, label, verbose, interactive, streaming)
        usage_summary = get_last_usage_summary()
        # Build chapter_id → asvs_key mapping for write_audit_result
        key_map = {_chapter_id(k): k for k in asvs_keys}
        log_event("grouped_audit.by_component.completed", {
            "component_id": component_id, "response_chars": len(response),
        })
    except Exception as exc:
        usage_summary = get_last_usage_summary()
        log_event("grouped_audit.by_component.failed", {
            "component_id": component_id, "error": str(exc),
        })
        console.print(f"[bold red]❌ {label} — {exc}[/bold red]")
        return [{"operation": "grouped_audit_failed", "component_id": component_id,
                 "asvs_keys": asvs_keys, "error": str(exc), "usage": usage_summary}]

    changed_paths = {
        chapter_id: path
        for chapter_id, path in zip(chapter_ids, expected_paths)
        if _path_changed(expected_snapshot, path)
    }

    grouped = None
    parse_error = None
    if response.strip():
        try:
            grouped = GroupedAuditOutput.parse_grouped(response)
        except Exception as exc:
            parse_error = exc

    if grouped is None and changed_paths:
        console.print(
            f"[dim]Detected direct file writes for {len(changed_paths)} chapter(s); skipping stdout JSON parsing.[/dim]"
        )
        results: list[dict] = []
        for ch in chapter_ids:
            asvs_key = key_map[ch]
            if ch not in changed_paths:
                console.print(f"  [yellow]⚠ {component_id} → {ch} was not updated[/yellow]")
                continue
            console.print(f"  [green]✓ {component_id} → {ch}[/green]")
            results.append({
                "operation": "grouped_audit",
                "component_id": component_id,
                "asvs_key": asvs_key,
                "prompt_chars": len(prompt),
                "response_chars": len(response),
                "usage": usage_summary,
            })
        return results

    if grouped is None:
        error = parse_error or ValueError("LLM returned no JSON and did not update any expected analysis files")
        log_event("grouped_audit.by_component.failed", {
            "component_id": component_id, "error": str(error),
        })
        console.print(f"[bold red]❌ {label} — {error}[/bold red]")
        return [{"operation": "grouped_audit_failed", "component_id": component_id,
                 "asvs_keys": asvs_keys, "error": str(error), "usage": usage_summary}]

    results: list[dict] = []
    for audit_output in grouped.results:
        ch = audit_output.asvs_chapter
        asvs_key = key_map.get(ch)
        if not asvs_key:
            console.print(f"  [yellow]⚠ LLM returned unknown chapter '{ch}', skipping write[/yellow]")
            continue
        try:
            write_audit_result(app_name, component_id, asvs_key, audit_output)
            console.print(f"  [green]✓ {component_id} → {ch}[/green]")
            results.append({
                "operation": "grouped_audit",
                "component_id": component_id,
                "asvs_key": asvs_key,
                "prompt_chars": len(prompt),
                "response_chars": len(response),
                "usage": usage_summary,
            })
        except Exception as exc:
            console.print(f"  [red]✗ write failed for {component_id}/{ch}: {exc}[/red]")

    return results
