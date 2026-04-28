#!/usr/bin/env python3
"""
cli.py — ASVS Security Audit Pipeline
──────────────────────────────────────
Commands (one per README step):

  extract  <app_name>            Step 1 — Generate static context via run_mapper.py
  triage   <app_name>            Step 2 — Architect agent: identify components  
  audit    <app_name>            Step 4 — Audit loop: component × ASVS chapter
  chat     <app_name>            Interactive chat mode for analysis discussion
  run      <app_name>            Full pipeline (extract → triage → audit)

Interactive Features:
  --verbose   (-v)               Show AI's internal reasoning and analysis
  --interactive (-i)             Allow AI to ask clarifying questions

Quick-start:
  pip install -r cli/requirements.txt
  export OPENAI_API_KEY=sk-...
  python cli.py extract  my-app --source-dir ~/code/my-app
  python cli.py triage   my-app --verbose --interactive
  python cli.py audit    my-app --verbose  
  python cli.py chat     my-app --component auth_module
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow `python cli.py` from the repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent))

import click
from rich.console import Console

from cli.commands import audit_cmd, extract_cmd, triage_cmd, chat_cmd, report_cmd

console = Console()


@click.group()
@click.version_option("0.1.0", prog_name="asvs-audit")
def main() -> None:
    """ASVS v5.0 semi-automated security audit pipeline."""


main.add_command(extract_cmd)
main.add_command(triage_cmd)
main.add_command(audit_cmd)
main.add_command(chat_cmd)
main.add_command(report_cmd)


# ── Convenience: full pipeline ────────────────────────────────────────────────

@main.command("run")
@click.argument("app_name")
@click.option("--source-dir", default=None, help="Path to app source (passed to extract).")
@click.option("--component", "component_filter", default=None)
@click.option("--chapter", "chapter_filter", default=None)
@click.pass_context
def run_cmd(
    ctx: click.Context,
    app_name: str,
    source_dir: str | None,
    component_filter: str | None,
    chapter_filter: str | None,
) -> None:
    """Full pipeline: extract → triage → audit."""
    console.rule("[bold cyan]Step 1 — Extract[/bold cyan]")
    ctx.invoke(extract_cmd, app_name=app_name, source_dir=source_dir, fmt="txt")

    console.rule("[bold cyan]Step 2 — Triage[/bold cyan]")
    ctx.invoke(triage_cmd, app_name=app_name, dry_run=False)

    console.rule("[bold cyan]Step 4 — Audit[/bold cyan]")
    ctx.invoke(
        audit_cmd,
        app_name=app_name,
        component_filter=component_filter,
        chapter_filter=chapter_filter,
        dry_run=False,
    )


if __name__ == "__main__":
    main()
