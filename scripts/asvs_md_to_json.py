#!/usr/bin/env python3
"""
Convert ASVS v5 markdown files to a structured JSON.

Usage:
    python asvs_md_to_json.py [--input-dir <dir>] [--output <file>]

Defaults:
    --input-dir  ../asvs5.0/en
    --output     ../ASVS_V5.json
"""

import argparse
import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

# Matches the top-level chapter heading:  # V6 Authentication
RE_CHAPTER = re.compile(r"^#\s+(V\d+)\s+(.+)$")

# Matches a sub-section heading:          ## V6.2 Password Security
RE_SECTION = re.compile(r"^##\s+(V\d+\.\d+)\s+(.+)$")

# Matches a requirement table row:        | **6.2.1** | Verify that... | 1 |
RE_REQ_ROW = re.compile(
    r"^\|\s*\*\*(\d+\.\d+\.\d+)\*\*\s*\|\s*(.+?)\s*\|\s*(\d+)\s*\|"
)

# Table separator / header rows to skip
RE_TABLE_SEP = re.compile(r"^\|[\s\-|:]+\|$")
RE_TABLE_HDR = re.compile(r"^\|\s*#\s*\|")


def _clean(text: str) -> str:
    """Strip leading/trailing whitespace and collapse internal runs."""
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_file(path: Path) -> dict:
    """Parse a single ASVS chapter markdown file and return a chapter dict."""
    lines = path.read_text(encoding="utf-8").splitlines()

    chapter: dict = {
        "file": path.name,
        "id": None,
        "title": None,
        "control_objective": "",
        "sections": [],
    }

    current_section: dict | None = None
    buffer: list[str] = []          # accumulates plain-text lines for descriptions
    in_objective: bool = False       # True while collecting control-objective text
    in_section_desc: bool = False    # True while collecting section intro text

    def flush_buffer(target: dict, key: str) -> None:
        text = _clean(" ".join(buffer))
        if text:
            target[key] = (target.get(key) or "") + (" " if target.get(key) else "") + text
        buffer.clear()

    for raw in lines:
        line = raw.rstrip()

        # ---- Chapter heading ------------------------------------------
        m = RE_CHAPTER.match(line)
        if m:
            chapter["id"] = m.group(1)
            chapter["title"] = _clean(m.group(2))
            in_objective = False
            in_section_desc = False
            buffer.clear()
            continue

        # ---- "## Control Objective" special section -------------------
        if re.match(r"^##\s+Control Objective", line):
            if current_section:
                flush_buffer(current_section, "description")
            in_objective = True
            in_section_desc = False
            buffer.clear()
            continue

        # ---- Sub-section heading  -------------------------------------
        m = RE_SECTION.match(line)
        if m:
            # flush pending text into previous context
            if in_objective:
                flush_buffer(chapter, "control_objective")
                in_objective = False
            elif current_section and in_section_desc:
                flush_buffer(current_section, "description")

            current_section = {
                "id": m.group(1),
                "title": _clean(m.group(2)),
                "description": "",
                "requirements": [],
            }
            chapter["sections"].append(current_section)
            in_section_desc = True
            buffer.clear()
            continue

        # ---- Table separator / header rows – skip ---------------------
        if RE_TABLE_SEP.match(line) or RE_TABLE_HDR.match(line):
            continue

        # ---- Requirement row ------------------------------------------
        m = RE_REQ_ROW.match(line)
        if m:
            if in_section_desc and current_section:
                flush_buffer(current_section, "description")
                in_section_desc = False
            req_id, description, level = m.group(1), _clean(m.group(2)), int(m.group(3))
            if current_section is not None:
                current_section["requirements"].append(
                    {"id": req_id, "description": description, "level": level}
                )
            continue

        # ---- Blank line ----------------------------------------------
        if not line.strip():
            # A blank line ends the current text block; we keep the buffer
            # so multi-paragraph text is joined with a space.
            continue

        # ---- Plain text / note lines ---------------------------------
        if line.startswith("|"):
            # Any other table line (e.g. multi-line cell continuation) – skip
            continue

        if in_objective or in_section_desc:
            # Strip leading markdown list markers for cleaner text
            clean_line = re.sub(r"^[\*\-]\s+", "", line).strip()
            if clean_line:
                buffer.append(clean_line)

    # Flush any remaining buffer
    if in_objective:
        flush_buffer(chapter, "control_objective")
    elif current_section and in_section_desc:
        flush_buffer(current_section, "description")

    # Remove empty description fields
    for sec in chapter["sections"]:
        if not sec["description"]:
            del sec["description"]
    if not chapter["control_objective"]:
        del chapter["control_objective"]

    return chapter


def sort_key(chapter: dict) -> int:
    """Sort chapters numerically by the digit(s) in their id (V1, V2, …)."""
    m = re.search(r"\d+", chapter.get("id") or "")
    return int(m.group()) if m else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Convert ASVS v5 markdown files to JSON.")
    p.add_argument(
        "--input-dir",
        default=str(Path(__file__).parent.parent / "asvs5.0" / "en"),
        help="Directory containing the ASVS markdown files (default: ../asvs5.0/en)",
    )
    p.add_argument(
        "--output-dir",
        default=str(Path(__file__).parent.parent / "asvs5.0" / "json"),
        help="Output directory for per-chapter JSON files (default: ../asvs5.0/json)",
    )
    p.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation level (default: 2)",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        sys.exit(f"Error: input directory not found: {input_dir}")

    md_files = sorted(input_dir.glob("0x*.md"))
    if not md_files:
        sys.exit(f"Error: no markdown files matching 0x*.md found in {input_dir}")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for f in md_files:
        chapter = parse_file(f)
        if not chapter["id"]:
            print(f"  Warning: no chapter heading found in {f.name}", file=sys.stderr)
            continue

        payload: dict = {
            "version": "5.0",
            "source": "https://github.com/OWASP/ASVS",
            "chapter": chapter,
        }

        out_path = out_dir / f.with_suffix(".json").name
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=args.indent),
            encoding="utf-8",
        )

        total_reqs = sum(len(sec["requirements"]) for sec in chapter["sections"])
        print(
            f"  {out_path.name}  "
            f"({len(chapter['sections'])} sections, {total_reqs} requirements)"
        )
        written += 1

    print(f"\nDone. {written} JSON files → {out_dir}")


if __name__ == "__main__":
    main()
