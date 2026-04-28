#!/usr/bin/env python3
"""
tree_size.py - Directory tree generator with file sizes (lines and bytes).
Excludes non-code directories and files generically for many languages.

Usage:
    python tree_size.py [path] [options]

Examples:
    python tree_size.py .
    python tree_size.py /my/project --output json --out tree.json
    python tree_size.py /my/project --output txt --out tree.txt
    python tree_size.py /my/project --output md
    python tree_size.py /my/project --max-depth 4
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Exclusion lists (directories and files to skip)
# ---------------------------------------------------------------------------

EXCLUDED_DIRS = {
    # Package managers / dependencies
    "node_modules",
    ".npm",
    ".yarn",
    "bower_components",
    "jspm_packages",
    "vendor",
    "packages",
    # Python
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".env",
    "site-packages",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pypackages__",
    # Build / dist / output
    "dist",
    "build",
    "out",
    "output",
    "target",
    "bin",
    "obj",
    "release",
    "debug",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".parcel-cache",
    ".cache",
    ".turbo",
    ".vercel",
    ".netlify",
    # Assets / media (usually not code)
    "assets",
    "static",
    "public",
    "media",
    "images",
    "img",
    "fonts",
    "icons",
    "videos",
    "audio",
    # Version control
    ".git",
    ".svn",
    ".hg",
    # IDE / editors
    ".idea",
    ".vscode",
    ".vs",
    ".eclipse",
    # Coverage / reports
    "coverage",
    ".nyc_output",
    "htmlcov",
    "reports",
    # Terraform / infra
    ".terraform",
    # Docker
    ".docker",
    # iOS / Android
    "Pods",
    "DerivedData",
    ".gradle",
    # Misc generated
    "generated",
    "gen",
    "auto-generated",
    "stubs",
    "typings",
    ".docusaurus",
    ".expo",
}

EXCLUDED_FILE_PATTERNS = {
    # Compiled / binary artifacts
    ".pyc", ".pyo", ".pyd",
    ".class", ".jar", ".war", ".ear",
    ".o", ".obj", ".a", ".so", ".dll", ".exe", ".lib",
    ".out", ".bin",
    # Lock files (usually not manually edited)
    # (we keep them but they can be excluded with --exclude-locks flag)
    # Image / media
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".bmp", ".tiff", ".tif", ".heic", ".raw",
    ".mp4", ".avi", ".mov", ".mkv", ".webm",
    ".mp3", ".wav", ".ogg", ".flac", ".aac",
    # Fonts
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    # Archives
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar",
    # Minified / map (generated)
    ".min.js", ".min.css", ".map",
    # Database / data dumps
    ".db", ".sqlite", ".sqlite3",
    ".sql",
    # Documents
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
}

LOCK_FILE_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Pipfile.lock",
    "poetry.lock",
    "composer.lock",
    "Gemfile.lock",
    "cargo.lock",
    "go.sum",
    "Podfile.lock",
}


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def is_excluded_dir(name: str) -> bool:
    return name.lower() in {d.lower() for d in EXCLUDED_DIRS}


def is_excluded_file(name: str, exclude_locks: bool) -> bool:
    name_lower = name.lower()
    # Check exact lock file names
    if exclude_locks and name_lower in {f.lower() for f in LOCK_FILE_NAMES}:
        return True
    # Check extension suffixes (handles .min.js etc.)
    for pattern in EXCLUDED_FILE_PATTERNS:
        if name_lower.endswith(pattern):
            return True
    return False


def count_lines(filepath: Path) -> int:
    """Count lines in a text file. Returns -1 if binary."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="strict") as f:
            return sum(1 for _ in f)
    except (UnicodeDecodeError, PermissionError):
        return -1  # binary or unreadable


def build_tree(
    root: Path,
    exclude_locks: bool = False,
    max_depth: int | None = None,
    current_depth: int = 0,
) -> dict:
    """Recursively build a tree dict for the given directory."""
    node = {
        "name": root.name or str(root),
        "type": "directory",
        "path": str(root),
        "children": [],
        "summary": {
            "total_files": 0,
            "total_bytes": 0,
            "total_lines": 0,
        },
    }

    if max_depth is not None and current_depth >= max_depth:
        node["truncated"] = True
        return node

    try:
        entries = sorted(root.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    except PermissionError:
        node["error"] = "Permission denied"
        return node

    for entry in entries:
        if entry.is_symlink():
            continue
        if entry.is_dir():
            if is_excluded_dir(entry.name):
                continue
            child = build_tree(entry, exclude_locks, max_depth, current_depth + 1)
            node["children"].append(child)
            node["summary"]["total_files"] += child["summary"]["total_files"]
            node["summary"]["total_bytes"] += child["summary"]["total_bytes"]
            node["summary"]["total_lines"] += child["summary"]["total_lines"]
        elif entry.is_file():
            if is_excluded_file(entry.name, exclude_locks):
                continue
            size_bytes = entry.stat().st_size
            lines = count_lines(entry)
            file_node = {
                "name": entry.name,
                "type": "file",
                "path": str(entry),
                "bytes": size_bytes,
                "lines": lines if lines >= 0 else None,  # None = binary
            }
            node["children"].append(file_node)
            node["summary"]["total_files"] += 1
            node["summary"]["total_bytes"] += size_bytes
            if lines >= 0:
                node["summary"]["total_lines"] += lines

    return node


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def render_txt(node: dict, prefix: str = "", is_last: bool = True) -> list[str]:
    """Render tree as plain text lines (like the `tree` command)."""
    connector = "└── " if is_last else "├── "
    extender = "    " if is_last else "│   "
    lines = []

    if node["type"] == "directory":
        s = node["summary"]
        info = (
            f"[{s['total_files']} files | "
            f"{_fmt_bytes(s['total_bytes'])} | "
            f"{s['total_lines']:,} lines]"
        )
        lines.append(f"{prefix}{connector}{node['name']}/ {info}")
        children = node.get("children", [])
        for i, child in enumerate(children):
            last = i == len(children) - 1
            lines.extend(render_txt(child, prefix + extender, last))
        if node.get("truncated"):
            lines.append(f"{prefix}{extender}... (max depth reached)")
    else:
        lines_info = f"{node['lines']:,} lines" if node["lines"] is not None else "binary"
        info = f"[{_fmt_bytes(node['bytes'])} | {lines_info}]"
        lines.append(f"{prefix}{connector}{node['name']} {info}")

    return lines


def format_txt(tree: dict) -> str:
    s = tree["summary"]
    header = [
        f"Directory: {tree['path']}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Total: {s['total_files']} files | "
        f"{_fmt_bytes(s['total_bytes'])} | "
        f"{s['total_lines']:,} lines",
        "",
        f"{tree['name']}/",
    ]
    children = tree.get("children", [])
    body = []
    for i, child in enumerate(children):
        last = i == len(children) - 1
        body.extend(render_txt(child, "", last))
    return "\n".join(header + body) + "\n"


def render_md(node: dict, depth: int = 0) -> list[str]:
    """Render tree as a Markdown nested list."""
    indent = "  " * depth
    lines = []

    if node["type"] == "directory":
        s = node["summary"]
        info = (
            f"**{node['name']}/** "
            f"— {s['total_files']} files, "
            f"{_fmt_bytes(s['total_bytes'])}, "
            f"{s['total_lines']:,} lines"
        )
        lines.append(f"{indent}- {info}")
        for child in node.get("children", []):
            lines.extend(render_md(child, depth + 1))
        if node.get("truncated"):
            lines.append(f"{indent}  - *(max depth reached)*")
    else:
        lines_info = f"{node['lines']:,} lines" if node["lines"] is not None else "binary"
        info = f"`{node['name']}` — {_fmt_bytes(node['bytes'])}, {lines_info}"
        lines.append(f"{indent}- {info}")

    return lines


def format_md(tree: dict) -> str:
    s = tree["summary"]
    header = [
        "# Directory Tree",
        "",
        f"**Path:** `{tree['path']}`  ",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Total:** {s['total_files']} files | "
        f"{_fmt_bytes(s['total_bytes'])} | "
        f"{s['total_lines']:,} lines",
        "",
        "## Tree",
        "",
    ]
    body = render_md(tree)
    return "\n".join(header + body) + "\n"


def format_json(tree: dict) -> str:
    meta = {
        "generated_at": datetime.now().isoformat(),
        "root": tree["path"],
        "summary": tree["summary"],
        "tree": tree,
    }
    return json.dumps(meta, indent=2, ensure_ascii=False)


def format_csv_flat(tree: dict) -> str:
    """Flat CSV with one row per file."""
    import csv, io
    rows = []

    def collect(node: dict):
        if node["type"] == "file":
            rows.append({
                "path": node["path"],
                "name": node["name"],
                "bytes": node["bytes"],
                "lines": node["lines"] if node["lines"] is not None else "",
            })
        for child in node.get("children", []):
            collect(child)

    collect(tree)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["path", "name", "bytes", "lines"])
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


FORMATTERS = {
    "txt": format_txt,
    "json": format_json,
    "md": format_md,
    "csv": format_csv_flat,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a directory tree with file sizes (lines and bytes).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Root directory to scan (default: current directory).",
    )
    parser.add_argument(
        "--output", "-o",
        choices=list(FORMATTERS.keys()),
        default="txt",
        help="Output format: txt (default), json, md, csv.",
    )
    parser.add_argument(
        "--out", "-f",
        metavar="FILE",
        help="Write output to FILE instead of stdout.",
    )
    parser.add_argument(
        "--max-depth", "-d",
        type=int,
        default=None,
        metavar="N",
        help="Maximum directory depth to traverse.",
    )
    parser.add_argument(
        "--exclude-locks",
        action="store_true",
        help="Also exclude lock files (package-lock.json, yarn.lock, etc.).",
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        metavar="DIR",
        help="Additional directory name to exclude (can be used multiple times).",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Extend exclusion list with user-supplied dirs
    for d in args.exclude_dir:
        EXCLUDED_DIRS.add(d)

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"Error: path '{root}' does not exist.", file=sys.stderr)
        sys.exit(1)
    if not root.is_dir():
        print(f"Error: '{root}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {root} ...", file=sys.stderr)
    tree = build_tree(root, exclude_locks=args.exclude_locks, max_depth=args.max_depth)

    formatter = FORMATTERS[args.output]
    content = formatter(tree)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(content, encoding="utf-8")
        print(f"Output written to {out_path}", file=sys.stderr)
    else:
        sys.stdout.write(content)


if __name__ == "__main__":
    main()
