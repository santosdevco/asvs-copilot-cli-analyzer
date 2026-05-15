"""
commands/report_md.py
─────────────────────
Generates a comprehensive Markdown report consolidating:
- Project index.json (components overview)
- Per-component context.yml (architecture, data flows)
- All audit chapters (V1.json - V17.json per component)

Usage:
  python cli.py report-md <app_name> [--output final.md]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console

from cli.config import OUTPUTS_DIR

console = Console()


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to read {path.name}: {e}[/yellow]")
        return None


def _safe_read_yaml(path: Path) -> dict[str, Any] | None:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to read {path.name}: {e}[/yellow]")
        return None


def _format_severity(sev: str) -> str:
    severity_map = {
        "CRITICAL": "🔴 CRITICAL",
        "HIGH": "🟠 HIGH",
        "MEDIUM": "🟡 MEDIUM",
        "LOW": "🟢 LOW",
    }
    return severity_map.get(sev, sev)


def _format_status(status: str) -> str:
    status_map = {
        "PASS": "✅ PASS",
        "FAIL": "❌ FAIL",
    }
    return status_map.get(status, status)


def _render_findings(results: list[dict[str, Any]]) -> str:
    """Render audit findings as markdown table."""
    if not results:
        return "(No findings)"

    md = "| Chapter | Req | Status | Severity | Title |\n"
    md += "|---------|-----|--------|----------|-------|\n"

    for result in results:
        chapter = result.get("req", "N/A").split(".")[0]  # V14 from 14.1.1
        req = result.get("req", "N/A")
        status = _format_status(result.get("status", "N/A"))
        sev = _format_severity(result.get("sev", "N/A"))
        title = result.get("tit", "N/A")
        md += f"| V{chapter} | {req} | {status} | {sev} | {title} |\n"

    return md


def _render_detailed_findings(results: list[dict[str, Any]]) -> str:
    """Render detailed audit findings with locations and hints."""
    if not results:
        return ""

    md = ""
    for i, result in enumerate(results, 1):
        req = result.get("req", "N/A")
        status = result.get("status", "N/A")
        sev = result.get("sev", "N/A")
        title = result.get("tit", "N/A")
        desc = result.get("desc", "")
        hint = result.get("hint", "")
        locations = result.get("locations", [])

        md += f"\n#### {i}. [{req}] {title}\n\n"
        md += f"**Status**: {_format_status(status)} | **Severity**: {_format_severity(sev)}\n\n"

        md += f"**Description**:\n{desc}\n\n"

        if locations:
            md += "**Locations**:\n"
            for loc in locations:
                file = loc.get("file", "N/A")
                func = loc.get("func", "N/A")
                lines = loc.get("lines", [])
                line_str = f" (lines {', '.join(map(str, lines))})" if lines else ""
                md += f"- `{file}` in `{func}`{line_str}\n"
            md += "\n"

        if hint:
            md += f"**Remediation**:\n{hint}\n"

        md += "\n---\n"

    return md


def _render_component_context(context: dict[str, Any]) -> str:
    """Render component context section."""
    md = ""

    if "component_name" in context:
        md += f"### {context['component_name']}\n\n"

    if "description" in context:
        md += f"**Description**: {context['description']}\n\n"

    if "architecture_role" in context:
        md += f"**Role**: {context['architecture_role']}\n\n"

    if "framework" in context:
        md += f"**Tech Stack**: {context['framework']}\n\n"

    if "data_flows" in context:
        df = context["data_flows"]
        if df:
            md += "#### Data Flows\n\n"

            if df.get("inputs"):
                md += "**Inputs**:\n"
                for inp in df["inputs"]:
                    md += f"- {inp}\n"
                md += "\n"

            if df.get("outputs"):
                md += "**Outputs**:\n"
                for out in df["outputs"]:
                    md += f"- {out}\n"
                md += "\n"

            if df.get("api_interactions"):
                md += "**API Interactions**:\n"
                for api in df["api_interactions"]:
                    md += f"- {api}\n"
                md += "\n"

    if "business_logic" in context:
        md += "#### Business Logic\n\n"
        for logic in context["business_logic"]:
            md += f"- {logic}\n"
        md += "\n"

    if "trust_boundaries" in context:
        md += "#### Trust Boundaries\n\n"
        for boundary in context["trust_boundaries"]:
            md += f"- {boundary}\n"
        md += "\n"

    if "access_control" in context:
        md += "#### Access Control\n\n"
        for ac in context["access_control"]:
            md += f"- {ac}\n"
        md += "\n"

    return md


def _load_component_analyses(app_name: str, component_id: str) -> dict[str, Any]:
    """Load all ASVS chapter analyses for a component."""
    analyses = {}
    analysis_dir = OUTPUTS_DIR / app_name / "components" / component_id / "analysis"

    if analysis_dir.exists():
        for v_file in sorted(analysis_dir.glob("V*.json")):
            chapter = v_file.stem  # V1, V2, etc.
            data = _safe_read_json(v_file)
            if data:
                analyses[chapter] = data

    return analyses


def _render_summary_stats(index_data: dict[str, Any]) -> str:
    """Render summary statistics."""
    md = ""

    components = index_data.get("project_triage", [])

    risk_counts = {}
    for comp in components:
        risk = comp.get("risk_level", "UNKNOWN")
        risk_counts[risk] = risk_counts.get(risk, 0) + 1

    md += "## Summary\n\n"
    md += f"**Total Components Audited**: {len(components)}\n\n"

    if risk_counts:
        md += "**Risk Distribution**:\n"
        for risk in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            count = risk_counts.get(risk, 0)
            if count > 0:
                md += f"- {_format_severity(risk)}: {count}\n"
        md += "\n"

    return md


@click.command("report-md")
@click.argument("app_name")
@click.option(
    "--output",
    "-o",
    default="final.md",
    help="Output markdown file (default: final.md)",
)
def report_md_cmd(app_name: str, output: str) -> None:
    """Generate comprehensive markdown report from audit results."""

    output_base = OUTPUTS_DIR / app_name
    if not output_base.exists():
        console.print(f"[red]Error: No audit data for '{app_name}'[/red]")
        sys.exit(1)

    index_path = output_base / "components" / "index.json"
    if not index_path.exists():
        console.print(f"[red]Error: index.json not found for '{app_name}'[/red]")
        sys.exit(1)

    index_data = _safe_read_json(index_path)
    if not index_data:
        console.print(f"[red]Error: Failed to read index.json[/red]")
        sys.exit(1)

    console.print(f"[cyan]Generating report for: {app_name}[/cyan]")

    # Build markdown report
    md = ""

    # Title and intro
    md += f"# ASVS Security Audit Report\n\n"
    md += f"**Project**: {app_name}\n"
    md += f"**Generated**: {__import__('datetime').datetime.now().isoformat()}\n\n"

    # Summary stats
    md += _render_summary_stats(index_data)

    # Table of contents
    md += "## Components\n\n"
    components = index_data.get("project_triage", [])
    for comp in components:
        comp_id = comp.get("component_id", "")
        comp_name = comp.get("component_name", "")
        risk = comp.get("risk_level", "UNKNOWN")
        md += f"- [{comp_name}](#{comp_id}) - {_format_severity(risk)}\n"

    md += "\n---\n\n"

    # Per-component analysis
    md += "## Detailed Analysis\n\n"

    for comp in components:
        comp_id = comp.get("component_id", "")
        comp_name = comp.get("component_name", "")

        console.print(f"  Processing: {comp_name}...")

        md += f"## {comp_name}\n\n"
        md += f"**Risk Level**: {_format_severity(comp.get('risk_level', 'UNKNOWN'))}\n"
        md += f"**Component ID**: `{comp_id}`\n\n"

        # Load and render context
        context_path = output_base / "components" / comp_id / "context.yml"
        context = _safe_read_yaml(context_path) or {}
        if context:
            md += _render_component_context(context)

        # Load all analyses
        analyses = _load_component_analyses(app_name, comp_id)

        if analyses:
            md += "### ASVS Audit Results\n\n"

            # Summary table of all chapters
            md += "#### Summary by Chapter\n\n"
            md += "| Chapter | Status Summary |\n"
            md += "|---------|----------------|\n"

            for chapter in sorted(analyses.keys()):
                data = analyses[chapter]
                results = data.get("results", [])

                if results:
                    pass_count = sum(1 for r in results if r.get("status") == "PASS")
                    fail_count = sum(1 for r in results if r.get("status") == "FAIL")
                    status_str = f"{pass_count} PASS, {fail_count} FAIL"
                else:
                    status_str = "No findings"

                md += f"| {chapter} | {status_str} |\n"

            md += "\n"

            # Detailed findings per chapter
            for chapter in sorted(analyses.keys()):
                data = analyses[chapter]
                results = data.get("results", [])

                if results:
                    md += f"#### {chapter} - Findings\n\n"
                    md += _render_findings(results)
                    md += "\n"
                    md += _render_detailed_findings(results)
                    md += "\n"

        md += "\n---\n\n"

    # Write output
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        output_path.write_text(md, encoding="utf-8")
        console.print(f"[green]✓ Report written to: {output_path.absolute()}[/green]")
    except Exception as e:
        console.print(f"[red]Error writing report: {e}[/red]")
        sys.exit(1)
