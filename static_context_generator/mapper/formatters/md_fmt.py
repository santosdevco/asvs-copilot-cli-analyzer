"""
formatters/md_fmt.py — Markdown report formatter.
"""
from __future__ import annotations

from .base import _render_tree_lines
from ..core.fs import fmt_bytes


def format_md(data: dict) -> str:
    identity  = data["identity"]
    structure = data["structure"]
    signals   = data["code_signals"]
    security  = data["security"]
    git       = data["git"]
    meta      = data["meta"]
    imports   = data["imports"]

    lines = [
        f"# Project Map: `{identity['name']}`",
        "",
        f"> **Generated:** {meta['generated_at']}  ",
        f"> **Root:** `{meta['root']}`  ",
        f"> **Scanner:** v{meta['scanner_version']}",
        "",
        "---",
        "",
        "## Identity",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Name | `{identity['name']}` |",
        f"| Type | `{identity['type']}` |",
        f"| Primary language | `{identity['primary_language']}` |",
        f"| Detected frameworks | {', '.join(f'`{f}`' for f in identity['frameworks']) or '—'} |",
        f"| Total files | {structure['total_files']:,} |",
        f"| Test ratio | {structure['test_ratio'] * 100:.0f}% ({structure['test_files_count']} test files) |",
        "",
        "## Language Distribution",
        "",
        "| Language | Files | Lines | % of lines |",
        "|----------|------:|------:|-----------:|",
    ]

    for lang, s in list(identity["language_distribution"].items())[:20]:
        bar = "█" * max(1, int(s["pct_lines"] / 4))
        lines.append(f"| {lang} | {s['files']} | {s['lines']:,} | {s['pct_lines']}% {bar} |")

    deps = identity["dependencies"]
    if deps["source_files"]:
        lines += [
            "",
            "## Dependencies",
            "",
            f"**Manifest files:** {', '.join(f'`{f}`' for f in deps['source_files'])}",
        ]
        if deps["production"]:
            prod_names = ", ".join(f"`{d['name']}`" for d in deps["production"][:25])
            suffix = "…" if len(deps["production"]) > 25 else ""
            lines.append(f"\n**Production ({len(deps['production'])}):** {prod_names}{suffix}")
        if deps["development"]:
            dev_names = ", ".join(f"`{d['name']}`" for d in deps["development"][:25])
            suffix = "…" if len(deps["development"]) > 25 else ""
            lines.append(f"\n**Development ({len(deps['development'])}):** {dev_names}{suffix}")
        if deps.get("npm_scripts"):
            lines.append(f"\n**npm scripts:** {', '.join(f'`{s}`' for s in deps['npm_scripts'])}")

    lines += ["", "## Architecture", ""]
    if structure["entry_points"]:
        lines.append("**Entry points:** " + ", ".join(f"`{e}`" for e in structure["entry_points"]))
    if structure["semantic_folders"]:
        lines.append("\n**Semantic folders detected:** " +
                     ", ".join(f"`{f}`" for f in structure["semantic_folders"]))
    if structure["infrastructure_files"]:
        lines.append("\n**Infrastructure / CI files:** " +
                     ", ".join(f"`{f}`" for f in structure["infrastructure_files"]))

    totals = signals.get("totals", {})
    lines += [
        "",
        "## Code Signals",
        "",
        "| Metric | Count |",
        "|--------|------:|",
        f"| Functions | {totals.get('functions', 0):,} |",
        f"| Classes / Structs / Interfaces | {totals.get('classes', 0):,} |",
        f"| TODO | {totals.get('TODO', 0)} |",
        f"| FIXME | {totals.get('FIXME', 0)} |",
        f"| HACK | {totals.get('HACK', 0)} |",
        f"| BUG | {totals.get('BUG', 0)} |",
    ]

    if signals.get("largest_files"):
        lines += ["", "**10 largest source files:**", ""]
        lines.append("| File | Lines | Language |")
        lines.append("|------|------:|----------|")
        for f in signals["largest_files"]:
            lines.append(f"| `{f['path']}` | {f['lines']:,} | {f['lang']} |")

    if signals.get("most_complex_files"):
        lines += ["", "**Most complex files (by function count):**", ""]
        lines.append("| File | Functions | Classes | Complexity keywords |")
        lines.append("|------|----------:|--------:|--------------------:|")
        for f in signals["most_complex_files"]:
            lines.append(
                f"| `{f['path']}` | {f['functions']} | {f['classes']} "
                f"| {f['complexity_keywords']} |"
            )

    if signals.get("todo_heavy_files"):
        lines += ["", "**Files with most TODOs/FIXMEs:**", ""]
        for f in signals["todo_heavy_files"][:5]:
            summary = ", ".join(f"{k}: {v}" for k, v in f["todos"].items())
            lines.append(f"- `{f['path']}` — {summary}")

    if imports.get("available"):
        lines += [
            "",
            "## Import Graph",
            "",
            f"- Internal dependency edges: **{imports['total_internal_edges']}**",
            f"- Unique external packages used: **{imports['unique_external_packages']}**",
        ]
        if imports.get("all_external_packages"):
            pkgs = ", ".join(f"`{p}`" for p in imports["all_external_packages"][:30])
            suffix = "…" if len(imports["all_external_packages"]) > 30 else ""
            lines.append(f"\n**External packages:** {pkgs}{suffix}")
        if imports.get("most_imported_modules"):
            lines += ["", "**Most imported internal modules:**", ""]
            for item in imports["most_imported_modules"][:10]:
                lines.append(f"- `{item['module']}` — imported {item['imported_by']} time(s)")

    if security.get("available"):
        lines += ["", "## Security Hints", ""]
        if security["exposed_env_files"]:
            files_list = ", ".join(f"`{f}`" for f in security["exposed_env_files"])
            lines.append(f"> ⚠️ **Real `.env` files found:** {files_list}")
        findings = security.get("potential_secrets", [])
        if findings:
            lines.append(f"\n**Potential hardcoded secrets — {len(findings)} finding(s):**\n")
            lines.append("| File | Line | Type | Snippet |")
            lines.append("|------|-----:|------|---------|")
            for f in findings[:20]:
                snippet = f["snippet"].replace("|", "\\|")
                lines.append(f"| `{f['file']}` | {f['line']} | `{f['type']}` | `{snippet}` |")
            if len(findings) > 20:
                lines.append(f"\n*… and {len(findings) - 20} more findings in the JSON output.*")
        else:
            lines.append("No hardcoded secret patterns detected.")

    if git.get("available"):
        lines += ["", "## Git Activity", ""]
        lines.append(f"- **Branch:** `{git['branch']}`")
        if git.get("first_commit_date"):
            lines.append(f"- **First commit:** {git['first_commit_date']}")
        if git.get("total_commits"):
            lines.append(f"- **Total commits:** {git['total_commits']:,}")
        if git.get("last_commit"):
            lines.append(f"- **Last commit:** `{git['last_commit']}`")
        if git.get("remote"):
            lines.append(f"- **Remote:** `{git['remote']}`")
        if git.get("top_contributors"):
            lines += ["", "**Top contributors:**", ""]
            for c in git["top_contributors"][:5]:
                lines.append(f"- {c['author']} — {c['commits']} commits")
        if git.get("most_active_files"):
            lines += ["", "**Most active files (by commit count):**", ""]
            for f in git["most_active_files"][:10]:
                lines.append(f"- `{f['file']}` — {f['commits']} commits")
        if git.get("recently_modified_files"):
            lines += ["", "**Recently modified (last 14 days):**", ""]
            for f in git["recently_modified_files"][:10]:
                lines.append(f"- `{f}`")

    tree = structure["tree"]
    lines += ["", "## Directory Tree", "", "```"]
    s = tree["summary"]
    lines.append(
        f"{tree['name']}/ [{s['files']} files | {fmt_bytes(s['bytes'])} | {s['lines']:,} lines]"
    )
    children = tree.get("children", [])
    for i, child in enumerate(children):
        lines.extend(_render_tree_lines(child, "", i == len(children) - 1))
    lines.append("```")

    return "\n".join(lines) + "\n"
