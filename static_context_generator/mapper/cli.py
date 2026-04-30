"""
cli.py — Argument parsing and main() entry point.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core.config import EXCLUDED_DIRS
from .orchestrator import _FILE_MANIFEST, generate_map, write_multi_file
from .formatters import FORMATTERS


def parse_args() -> argparse.Namespace:
    _valid_sections = [key for _, key, _, _ in _FILE_MANIFEST]

    parser = argparse.ArgumentParser(
        description="Comprehensive static analysis context map for AI agents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path", nargs="?", default=".", help="Root directory (default: .)")

    # Multi-file output (default)
    parser.add_argument(
        "--out-dir", metavar="DIR", default=None,
        help="Output directory for multi-file map (default: ./project_map)",
    )
    parser.add_argument(
        "--reports", metavar="SECTION", nargs="+",
        choices=_valid_sections,
        default=None,
        help=f"Only write these section(s). Valid values: {', '.join(_valid_sections)}",
    )
    parser.add_argument(
        "--format", metavar="FMT", dest="section_format",
        choices=["json", "txt"],
        default="json",
        help="Format for section files: json (default) or txt",
    )

    # Single-file fallback
    parser.add_argument("--single-file", action="store_true",
                        help="Write a single file instead of a directory")
    parser.add_argument(
        "--output", "-o",
        choices=list(FORMATTERS.keys()),
        default="json",
        help="Single-file format: json (default), compact, md, txt",
    )
    parser.add_argument("--out", "-f", metavar="FILE",
                        help="Single output file path (implies --single-file)")

    # Common options
    parser.add_argument("--max-depth", "-d", type=int, default=None, metavar="N",
                        help="Maximum directory depth for the tree")
    parser.add_argument("--exclude-locks", action="store_true",
                        help="Exclude lock files")
    parser.add_argument("--exclude-dir", action="append", default=[], metavar="DIR",
                        help="Additional directory to exclude (repeatable)")
    parser.add_argument("--no-git",      action="store_true", help="Skip git analysis")
    parser.add_argument("--no-security", action="store_true", help="Skip security scan")
    parser.add_argument("--no-imports",  action="store_true", help="Skip import graph")
    parser.add_argument("--no-per-file", action="store_true",
                        help="Omit per-file details from code_signals (smaller output)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    
    print(f"[DEBUG] Starting analysis...", file=sys.stderr)
    print(f"[DEBUG] Args: path={args.path}, reports={args.reports}, out_dir={args.out_dir}", file=sys.stderr)

    for d in args.exclude_dir:
        EXCLUDED_DIRS.add(d)

    root = Path(args.path).resolve()
    if not root.exists() or not root.is_dir():
        print(f"Error: '{root}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)
    
    print(f"[DEBUG] Root directory: {root}", file=sys.stderr)

    print(f"[DEBUG] Generating map...", file=sys.stderr)
    data = generate_map(
        root,
        exclude_locks=args.exclude_locks,
        max_depth=args.max_depth,
        no_git=args.no_git,
        no_security=args.no_security,
        no_imports=args.no_imports,
    )
    print(f"[DEBUG] Map generation complete", file=sys.stderr)

    use_single = args.single_file or bool(args.out)

    if use_single:
        if args.no_per_file:
            data["code_signals"].pop("per_file", None)
        content = FORMATTERS[args.output](data)
        if args.out:
            out_path = Path(args.out)
            out_path.write_text(content, encoding="utf-8")
            print(f"\nMap written to {out_path}", file=sys.stderr)
        else:
            sys.stdout.write(content)
    else:
        out_dir = Path(args.out_dir) if args.out_dir else Path("project_map")
        print(f"[DEBUG] Writing multi-file output to: {out_dir}", file=sys.stderr)
        write_multi_file(
            data,
            out_dir,
            no_per_file=args.no_per_file,
            fmt=args.section_format,
            only_reports=args.reports,
        )
        print(f"  Load {out_dir / '00_index.json'} first.", file=sys.stderr)
