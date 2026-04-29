"""
commands/extract.py  —  Step 1
──────────────────────────────
Calls run_mapper.py as a subprocess to produce static context .txt files.

Usage:
  python cli.py extract <app_name> [--source-dir PATH]
"""
from __future__ import annotations

from html import escape
import subprocess
import sys
import tempfile
from pathlib import Path

import click
from rich.console import Console

from cli.config import MAPPER_SCRIPT, OUTPUTS_DIR
from cli.core.app_logger import init_app_logger, log_event

console = Console()


def _report_type_from_file(path: Path) -> str:
    """Infer report type from mapper file name (e.g., 01_identity.txt -> identity)."""
    stem = path.stem
    if "_" not in stem:
        return stem.lower()
    return stem.split("_", 1)[1].lower()


def _to_cdata(text: str) -> str:
    """Wrap text as CDATA, safely handling nested CDATA terminators."""
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def _build_static_context_xml(source_dir: Path, source_fmt: str, xml_path: Path) -> Path | None:
    """Build consolidated static_context.xml from mapper section files."""
    report_files = sorted(
        f for f in source_dir.glob(f"*.{source_fmt}")
        if f.name != f"static_context.{source_fmt}" and f.name != "static_context.xml"
    )
    if not report_files:
        return None

    lines = ["<static_context>"]
    for path in report_files:
        report_type = escape(_report_type_from_file(path))
        filename = escape(path.name)
        content = path.read_text(encoding="utf-8")
        lines.append(f"  <report type=\"{report_type}\" filename=\"{filename}\">{_to_cdata(content.strip())}</report>")
        lines.append("")
    if lines[-1] == "":
        lines.pop()
    lines.append("</static_context>")

    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return xml_path


@click.command("extract")
@click.argument("app_name")
@click.option(
    "--source-dir",
    default=None,
    help="Path to the application source code. "
         "Defaults to the argument passed to run_mapper.py as-is.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["txt", "json", "xml"], case_sensitive=False),
    default="xml",
    show_default=True,
    help="Output format. xml generates only outputs/<app_name>/static_context.xml.",
)
def extract_cmd(app_name: str, source_dir: str | None, fmt: str) -> None:
    """Step 1 — Generate static context files from source code."""
    init_app_logger(
        app_name=app_name,
        command_name="extract",
        command_line=" ".join(sys.argv),
        options={"source_dir": source_dir, "format": fmt},
    )
    fmt = fmt.lower()
    app_dir = source_dir or app_name
    app_out_dir = OUTPUTS_DIR / app_name

    if fmt == "xml":
        xml_path = app_out_dir / "static_context.xml"
        with tempfile.TemporaryDirectory(prefix="mapper_static_") as tmpdir:
            temp_out_dir = Path(tmpdir)
            cmd = [
                sys.executable,
                str(MAPPER_SCRIPT),
                app_dir,
                "--format", "txt",
                "--out-dir", str(temp_out_dir),
            ]

            console.print(f"[bold cyan]extract[/bold cyan] → {' '.join(cmd)}")
            log_event(
                "extract.subprocess",
                {"cmd": cmd, "out_dir": str(temp_out_dir), "requested_format": fmt},
            )
            result = subprocess.run(cmd, check=False)

            if result.returncode != 0:
                log_event("extract.failed", {"returncode": result.returncode})
                console.print(f"[bold red]✗ run_mapper.py exited with code {result.returncode}[/bold red]")
                raise SystemExit(result.returncode)

            built_xml = _build_static_context_xml(temp_out_dir, "txt", xml_path)
            if not built_xml:
                console.print("[bold red]✗ No section files found to build static_context.xml[/bold red]")
                log_event("extract.xml_skipped", {"reason": "no_reports_found", "format": fmt})
                raise SystemExit(1)

        console.print(f"[bold green]✓ XML static context written to {xml_path}[/bold green]")
        log_event("extract.completed", {"returncode": 0, "xml_path": str(xml_path), "format": fmt})
        return

    out_dir = app_out_dir / "static_context"
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(MAPPER_SCRIPT),
        app_dir,
        "--format", fmt,
        "--out-dir", str(out_dir),
    ]

    console.print(f"[bold cyan]extract[/bold cyan] → {' '.join(cmd)}")
    log_event("extract.subprocess", {"cmd": cmd, "out_dir": str(out_dir), "requested_format": fmt})
    result = subprocess.run(cmd, check=False)

    if result.returncode != 0:
        log_event("extract.failed", {"returncode": result.returncode})
        console.print(f"[bold red]✗ run_mapper.py exited with code {result.returncode}[/bold red]")
        raise SystemExit(result.returncode)

    log_event("extract.completed", {"returncode": result.returncode, "format": fmt})
    console.print(f"[bold green]✓ Static context written to {out_dir}[/bold green]")
