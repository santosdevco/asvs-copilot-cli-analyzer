"""
commands/extract.py  —  Step 1
──────────────────────────────
Calls run_mapper.py as a subprocess to produce static context .txt files.

Usage:
  python cli.py extract <app_name> [--source-dir PATH]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

from cli.config import MAPPER_SCRIPT, OUTPUTS_DIR
from cli.core.app_logger import init_app_logger, log_event

console = Console()


@click.command("extract")
@click.argument("app_name")
@click.option(
    "--source-dir",
    default=None,
    help="Path to the application source code. "
         "Defaults to the argument passed to run_mapper.py as-is.",
)
@click.option("--format", "fmt", default="txt", show_default=True, help="Output format.")
def extract_cmd(app_name: str, source_dir: str | None, fmt: str) -> None:
    """Step 1 — Generate static context files from source code."""
    init_app_logger(
        app_name=app_name,
        command_name="extract",
        command_line=" ".join(sys.argv),
        options={"source_dir": source_dir, "format": fmt},
    )
    out_dir = OUTPUTS_DIR / app_name / "static_context"
    out_dir.mkdir(parents=True, exist_ok=True)

    app_dir = source_dir or app_name

    cmd = [
        sys.executable,
        str(MAPPER_SCRIPT),
        app_dir,
        "--format", fmt,
        "--out-dir", str(out_dir),
    ]

    console.print(f"[bold cyan]extract[/bold cyan] → {' '.join(cmd)}")
    log_event("extract.subprocess", {"cmd": cmd, "out_dir": str(out_dir)})
    result = subprocess.run(cmd, check=False)

    if result.returncode != 0:
        log_event("extract.failed", {"returncode": result.returncode})
        console.print(f"[bold red]✗ run_mapper.py exited with code {result.returncode}[/bold red]")
        raise SystemExit(result.returncode)

    log_event("extract.completed", {"returncode": result.returncode})
    console.print(f"[bold green]✓ Static context written to {out_dir}[/bold green]")
