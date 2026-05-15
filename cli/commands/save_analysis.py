"""
commands/save_analysis.py  —  Save analysis JSON result without interactive prompts
──────────────────────────────────────────────────────────────────────────────────

Non-interactive command to ingest analysis results from files or stdin.
Safe for large JSON: avoids shell argument size limits by reading from stdin or file.

Usage:
  # Via stdin (safe for big JSON)
  cat result.json | python cli.py save-analysis watshelp-bancodebogota-api --component room_message_management --chapter V1
  echo '{"results":[]}' | python cli.py save-analysis watshelp-bancodebogota-api --component room_message_management --chapter V1

  # Via file
  python cli.py save-analysis watshelp-bancodebogota-api --component room_message_management --chapter V1 --file result.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import click
from rich.console import Console

from cli.config import ANALYSIS_OUTPUT_FORMAT

console = Console(stderr=False)  # stdout for output JSON
console_err = Console(stderr=True)  # stderr for errors/status


def _extract_json(raw: str) -> tuple:
    """Extract JSON from raw text, including markdown code fences.

    Returns (data_or_raw_str, is_raw) where is_raw=True means JSON could not
    be identified and the caller should save the raw string as-is.
    """
    text = raw.strip()

    # 1. Direct JSON parse
    try:
        return json.loads(text), False
    except json.JSONDecodeError:
        pass

    # 2. Extract from markdown code fences (```json ... ``` or ``` ... ```)
    blocks = re.findall(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if len(blocks) == 1:
        try:
            return json.loads(blocks[0].strip()), False
        except json.JSONDecodeError:
            pass

    # Multiple blocks, no parseable block, or free-form text — save raw
    return raw, True


@click.command("save-analysis")
@click.argument("app_name")
@click.option(
    "--component",
    "component_id",
    required=True,
    help="Component ID to save analysis for.",
)
@click.option(
    "--chapter",
    "chapter_id",
    required=True,
    help="ASVS chapter ID (e.g., V1, V2, ..., V14).",
)
@click.option(
    "--file",
    "input_file",
    default=None,
    help="JSON file path. Reads stdin if omitted.",
)
def save_analysis_cmd(
    app_name: str,
    component_id: str,
    chapter_id: str,
    input_file: str | None,
) -> None:
    """Save analysis JSON result for a component/chapter without interactive prompts.

    Reads JSON from a file or stdin. Output is a single JSON line (for machine parsing).
    Errors are written to stderr.
    """
    try:
        # Read JSON from file or stdin
        if input_file:
            raw = Path(input_file).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()

        # Extract JSON (handles plain JSON, markdown code fences, and free-form text)
        data, is_raw = _extract_json(raw)
        if is_raw:
            console_err.print(
                "[yellow]⚠ Could not identify a single JSON object — saving raw content as-is.[/yellow]"
            )

        # Ensure output directory exists
        output_dir = Path(f"outputs/{app_name}/components/{component_id}/analysis")
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            console_err.print(f"[bold red]Error:[/bold red] Could not create directory: {e}")
            raise SystemExit(1)

        # Remove stale files for same chapter (any extension)
        for existing in output_dir.glob(f"{chapter_id}.*"):
            try:
                existing.unlink()
            except Exception:
                pass

        # Determine format and save
        target_format = ANALYSIS_OUTPUT_FORMAT if ANALYSIS_OUTPUT_FORMAT in ("json", "xml") else "json"
        output_file = output_dir / f"{chapter_id}.{target_format}"

        try:
            with open(output_file, "w", encoding="utf-8") as f:
                if is_raw or target_format == "xml":
                    f.write(raw)
                else:
                    json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            console_err.print(f"[bold red]Error:[/bold red] Could not write file: {e}")
            raise SystemExit(1)

        # Output result as JSON (one line for easy machine parsing)
        result = {
            "success": True,
            "saved": str(output_file),
            "component": component_id,
            "chapter": chapter_id,
            "format": target_format,
            "raw": is_raw,
        }
        print(json.dumps(result, ensure_ascii=False))

    except SystemExit:
        raise
    except Exception as e:
        console_err.print(f"[bold red]Unexpected error:[/bold red] {e}")
        raise SystemExit(1)
