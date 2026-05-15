"""
commands/list_components.py  —  List all components for a project
──────────────────────────────────────────────────────────────────

Quick read-only command to output a component list for a project, usable programmatically.

Usage:
  python cli.py list-components <app_name>
  python cli.py list-components <app_name> --format json
  python cli.py list-components <app_name> --format ids
"""
from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from cli.core import load_component_index
from cli.commands.audit import _scan_existing_analyses

console = Console()


def _display_component_table(
    app_name: str,
    components: list,
    analyses: dict,
) -> None:
    """Display components as a rich table."""
    if not components:
        console.print("[yellow]No components found.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Component ID", style="cyan", width=30)
    table.add_column("Name", style="bold")
    table.add_column("Risk Level", justify="center", width=10)
    table.add_column("Asset Tags", style="dim", width=20)
    table.add_column("Progress", justify="center")

    for component in components:
        from cli.core import get_applicable_asvs_keys

        applicable_chapters = get_applicable_asvs_keys(component.asset_tags)
        component_analyses = analyses.get(component.component_id, {})
        completed = len(component_analyses)
        total = len(applicable_chapters)

        risk_color = {
            "CRITICAL": "red",
            "HIGH": "yellow",
            "MEDIUM": "blue",
            "LOW": "green"
        }.get(component.risk_level, "white")

        progress_text = f"{completed}/{total}"
        if total > 0:
            progress_text += f" ({completed/total*100:.0f}%)"

        tags_text = ", ".join(component.asset_tags[:2])
        if len(component.asset_tags) > 2:
            tags_text += f" (+{len(component.asset_tags)-2})"

        table.add_row(
            component.component_id,
            component.component_name[:40],
            f"[{risk_color}]{component.risk_level}[/{risk_color}]",
            tags_text,
            progress_text
        )

    console.print(table)


def _display_component_json(
    components: list,
    analyses: dict,
) -> None:
    """Display components as JSON."""
    from cli.core import get_applicable_asvs_keys

    result = []
    for component in components:
        applicable_chapters = get_applicable_asvs_keys(component.asset_tags)
        component_analyses = analyses.get(component.component_id, {})

        result.append({
            "component_id": component.component_id,
            "component_name": component.component_name,
            "risk_level": component.risk_level,
            "asset_tags": component.asset_tags,
            "files_to_audit": component.files_to_audit,
            "analysis_progress": {
                "completed": len(component_analyses),
                "total": len(applicable_chapters),
            },
        })

    console.print(json.dumps(result, indent=2, ensure_ascii=False))


def _display_component_ids(components: list) -> None:
    """Display just component IDs, one per line."""
    for component in components:
        console.print(component.component_id)


def _display_component_names(components: list) -> None:
    """Display just component names, one per line."""
    for component in components:
        console.print(component.component_name)


@click.command("list-components")
@click.argument("app_name")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["table", "json", "ids", "names"]),
    default="table",
    help="Output format: table (default), json, ids (component IDs), or names (component names).",
)
def list_components_cmd(app_name: str, fmt: str) -> None:
    """List all components for a project."""
    try:
        component_index = load_component_index(app_name)
    except FileNotFoundError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise SystemExit(1)

    if not component_index.project_triage:
        console.print("[yellow]No components found.[/yellow]")
        return

    # Scan existing analyses for progress
    analyses = _scan_existing_analyses(app_name)

    if fmt == "table":
        _display_component_table(app_name, component_index.project_triage, analyses)
    elif fmt == "json":
        _display_component_json(component_index.project_triage, analyses)
    elif fmt == "ids":
        _display_component_ids(component_index.project_triage)
    elif fmt == "names":
        _display_component_names(component_index.project_triage)

    if fmt == "table":
        console.print(f"\n[dim]{len(component_index.project_triage)} component(s) found[/dim]")
