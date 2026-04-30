"""
orchestrator.py — High-level data assembly and multi-file writer.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from .core.config import SCRIPT_VERSION
from .core.fs import collect_files, fmt_bytes
from .analyzers.structure import build_tree, analyze_languages
from .analyzers.dependencies import find_dependencies, detect_frameworks
from .analyzers.architecture import analyze_architecture
from .analyzers.endpoints import analyze_endpoints
from .analyzers.env_vars import analyze_env_vars
from .analyzers.database import analyze_database
from .analyzers.middlewares import analyze_middlewares
from .analyzers.imports import build_import_graph
from .analyzers.code_signals import analyze_code_signals
from .analyzers.security import scan_security
from .analyzers.git import analyze_git
from .analyzers.frontend import analyze_frontend
from .formatters import SECTION_TXT_FORMATTERS


# ── Manifest of output files ──────────────────────────────────────────────────
_FILE_MANIFEST: list[tuple[str, str, str, str]] = [
    (
        "01_identity.json",
        "identity",
        "Project identity",
        "Understanding the project stack, language, frameworks and installed packages.",
    ),
    (
        "02_structure.json",
        "structure",
        "Directory structure & architecture",
        "Navigating the codebase, finding files, understanding folder conventions and entry points.",
    ),
    (
        "03_endpoints.json",
        "endpoints",
        "HTTP API endpoints",
        "Working with API routes: adding/modifying endpoints, understanding URL layout.",
    ),
    (
        "04_env_vars.json",
        "env_vars",
        "Environment variables",
        "Working with configuration, deployment, or understanding runtime dependencies.",
    ),
    (
        "05_database.json",
        "database",
        "Database schema and SQL usage",
        "Writing queries, understanding the data model, adding migrations.",
    ),
    (
        "06_middlewares.json",
        "middlewares",
        "Middleware chains in routes",
        "Adding or modifying middleware, understanding auth/permission flows.",
    ),
    (
        "07_imports.json",
        "imports",
        "Internal import graph",
        "Understanding module coupling, refactoring, tracing dependencies.",
    ),
    (
        "08_code_signals.json",
        "code_signals",
        "Code signals (complexity, TODOs)",
        "Code quality review, identifying god-objects, tracking tech debt.",
    ),
    (
        "09_security.json",
        "security",
        "Security findings",
        "Security audit, reviewing credential handling, finding hardcoded secrets.",
    ),
    (
        "10_git.json",
        "git",
        "Git activity",
        "Understanding recent changes, hot files, and contributors.",
    ),
    (
        "11_frontend.json",
        "frontend",
        "Frontend security (XSS, DOM leaks, client routes)",
        "XSS sink audit, unsafe storage, postMessage gaps, React/Vue/Angular-specific findings.",
    ),
]


def _j(obj: object) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


def _format_index_txt(index: dict, data: dict) -> str:
    """Generate compact TXT index optimized for AI context."""
    lines = []
    
    # Project overview
    project = index["project"]
    frameworks = ", ".join(project["frameworks"]) if project["frameworks"] else "none"
    lines.append(f"PROJECT: {project['name']} | TYPE: {project['type']} | LANG: {project['primary_language']} | FRAMEWORKS: {frameworks}")
    
    # Instructions for AI
    lines.append("USAGE: Load sections as needed based on task requirements")
    lines.append("")
    
    # File listing with key stats
    lines.append("FILES:")
    for file_info in index["files"]:
        filename = file_info["file"]
        title = file_info["title"]
        stats = file_info["stats"]
        
        # Create compact stats string
        stat_parts = []
        for key, value in stats.items():
            if value and value != 0 and value != False:
                if isinstance(value, list):
                    if value:  # Non-empty list
                        stat_parts.append(f"{key}:{len(value)}")
                elif isinstance(value, str):
                    stat_parts.append(f"{key}:{value}")
                else:
                    stat_parts.append(f"{key}:{value}")
        
        stats_str = "|".join(stat_parts) if stat_parts else "no data"
        lines.append(f"  {filename}: {title} [{stats_str}]")
    
    return "\n".join(lines) + "\n"


def generate_map(
    root: Path,
    exclude_locks: bool = False,
    max_depth: Optional[int] = None,
    no_git: bool = False,
    no_security: bool = False,
    no_imports: bool = False,
) -> dict:
    total_steps = 11 - int(no_git) - int(no_security) - int(no_imports)
    step = 0

    def log(msg: str) -> None:
        nonlocal step
        step += 1
        print(f"  [{step}/{total_steps}] {msg}", file=sys.stderr)

    print(f"Scanning {root} ...", file=sys.stderr)
    files = collect_files(root, exclude_locks)
    print(f"  Found {len(files)} files.", file=sys.stderr)

    log("Building directory tree ...")
    tree = build_tree(root, exclude_locks, max_depth)
    tree["path"] = str(root)

    log("Analyzing languages ...")
    lang_info = analyze_languages(files)

    log("Parsing dependencies and detecting frameworks ...")
    deps = find_dependencies(root)
    frameworks = detect_frameworks(deps)

    log("Analyzing architecture ...")
    arch = analyze_architecture(root, files)

    log("Detecting API endpoints ...")
    endpoints = analyze_endpoints(files, root)

    log("Extracting environment variables ...")
    env_vars = analyze_env_vars(files, root)

    log("Analyzing database / SQL usage ...")
    is_frontend = arch["type"] == "frontend"
    database = analyze_database(files, root, is_frontend=is_frontend)

    log("Mapping middleware chains ...")
    middlewares = analyze_middlewares(files, root)

    import_data: dict = {"available": False}
    if not no_imports:
        log("Building import graph ...")
        import_data = build_import_graph(files, root)
        import_data["available"] = True

    log("Analyzing code signals ...")
    code_signals = analyze_code_signals(files, root)

    frontend = analyze_frontend(
        files, root, frameworks=frameworks, is_frontend=is_frontend
    )

    security: dict = {"available": False}
    if not no_security:
        log("Scanning security hints ...")
        security = scan_security(files, root)
        security["available"] = True

    git: dict = {"available": False}
    if not no_git:
        log("Reading git history ...")
        git = analyze_git(root)

    meta = {
        "generated_at": datetime.now().isoformat(),
        "root": str(root),
        "scanner_version": SCRIPT_VERSION,
    }

    return {
        "meta": meta,
        "identity": {
            "name": root.name,
            "type": arch["type"],
            "primary_language": lang_info["primary"],
            "language_distribution": lang_info["distribution"],
            "frameworks": frameworks,
            "dependencies": {
                "source_files": deps["source_files"],
                "npm_scripts": deps.get("npm_scripts", []),
                "production": deps["production"][:150],
                "development": deps["development"][:150],
            },
        },
        "structure": {
            "tree": tree,
            "entry_points": arch["entry_points"],
            "semantic_folders": arch["semantic_folders"],
            "infrastructure_files": arch["infrastructure_files"],
            "total_files": len(files),
            "test_files_count": arch["test_files_count"],
            "source_files_count": arch["source_files_count"],
            "test_ratio": arch["test_ratio"],
        },
        "endpoints":    endpoints,
        "env_vars":     env_vars,
        "database":     database,
        "middlewares":  middlewares,
        "imports":      import_data,
        "code_signals": code_signals,
        "security":     security,
        "git":          git,
        "frontend":     frontend,
    }


def write_multi_file(
    data: dict,
    out_dir: Path,
    no_per_file: bool = False,
    fmt: str = "json",
    only_reports: Optional[list[str]] = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    if no_per_file:
        data["code_signals"].pop("per_file", None)

    ext = "txt" if fmt == "txt" else "json"

    index_files = []
    for filename_json, key, title, use_when in _FILE_MANIFEST:
        if only_reports and key not in only_reports:
            continue

        section  = data.get(key, {})
        stem     = filename_json.replace(".json", "")
        filename = f"{stem}.{ext}"

        # Always use the chosen format - generate TXT for all sections when fmt=txt
        if fmt == "txt":
            if key in SECTION_TXT_FORMATTERS:
                content = SECTION_TXT_FORMATTERS[key](section, data["meta"])
            else:
                # Fallback: create simple key-value TXT for sections without formatters
                content = f"{key.upper().replace('_', ' ')}: {len(str(section))} bytes of data\n"
        else:
            payload = {
                "_meta": {**data["meta"], "section": key},
                key: section,
            }
            content = _j(payload)

        (out_dir / filename).write_text(content, encoding="utf-8")

        stats: dict = {}
        if key == "identity":
            stats = {
                "primary_language": section.get("primary_language"),
                "frameworks":       section.get("frameworks", []),
                "production_deps":  len(section.get("dependencies", {}).get("production", [])),
            }
        elif key == "structure":
            stats = {
                "total_files":  section.get("total_files"),
                "entry_points": section.get("entry_points", []),
            }
        elif key == "endpoints":
            stats = {
                "total_endpoints": section.get("total", 0),
                "domains":         list(section.get("domain_map", {}).keys()),
            }
        elif key == "env_vars":
            stats = {
                "unique_vars":      section.get("total_unique_vars", 0),
                "total_references": section.get("total_references", 0),
            }
        elif key == "database":
            stats = {
                "schema_tables":  section.get("total_schema_tables", 0),
                "tables_used":    section.get("total_tables_used", 0),
                "orm_detected":   section.get("orm_odm", {}).get("detected", []),
            }
        elif key == "middlewares":
            stats = {
                "distinct_middlewares": section.get("total_middlewares_detected", 0),
                "routes_protected":     len(section.get("routes_with_middleware", [])),
            }
        elif key == "imports":
            stats = {
                "internal_edges":    section.get("total_internal_edges", 0),
                "external_packages": section.get("unique_external_packages", 0),
            }
        elif key == "code_signals":
            t = section.get("totals", {})
            stats = {
                "functions": t.get("functions", 0),
                "classes":   t.get("classes", 0),
                "todos":     t.get("TODO", 0) + t.get("FIXME", 0) + t.get("HACK", 0),
            }
        elif key == "security":
            stats = {
                "total_findings":    section.get("total_findings", 0),
                "exposed_env_files": len(section.get("exposed_env_files", [])),
            }
        elif key == "git":
            stats = {
                "available":     section.get("available", False),
                "branch":        section.get("branch"),
                "total_commits": section.get("total_commits"),
            }

        index_files.append({
            "file":     filename,
            "section":  key,
            "title":    title,
            "use_when": use_when,
            "stats":    stats,
        })

    index = {
        "_meta": data["meta"],
        "project": {
            "name":             data["identity"]["name"],
            "type":             data["identity"]["type"],
            "primary_language": data["identity"]["primary_language"],
            "frameworks":       data["identity"]["frameworks"],
        },
        "instructions": (
            "Load 00_index.json first to understand the project. "
            "Then load only the section files relevant to your task using "
            "the 'use_when' field as guidance. "
            "Avoid loading all files at once unless doing a full audit."
        ),
        "files": index_files,
    }
    # Generate index file in chosen format
    index_filename = f"00_index.{ext}"
    if fmt == "txt":
        # Create compact TXT index
        index_content = _format_index_txt(index, data)
    else:
        index_content = _j(index)
    
    (out_dir / index_filename).write_text(index_content, encoding="utf-8")

    # Count all files with the chosen extension
    pattern = f"*.{ext}"
    total_size = sum(f.stat().st_size for f in out_dir.glob(pattern))
    print(
        f"\n  Written {len(index_files) + 1} files to {out_dir}  "
        f"(total {fmt_bytes(total_size)})",
        file=sys.stderr,
    )
    if fmt == "txt":
        print(f"  Load {out_dir}/00_index.txt first.", file=sys.stderr)
