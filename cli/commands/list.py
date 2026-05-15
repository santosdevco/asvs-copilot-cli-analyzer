"""
commands/list.py  —  List and filter audit results (interactive TUI)
────────────────────────────────────────────────────────────────────────
Query audit results to find failed requirements, list by chapter/requirement,
filter by component, and copy results for use elsewhere.

Usage:
  python cli.py list <app_name>                    # Interactive TUI
  python cli.py list <app_name> --failures-only    # Show only FAILED requirements
  python cli.py list <app_name> --chapter V1       # Filter by chapter (non-interactive)
  python cli.py list <app_name> --copy V1              # Copy failed V1 results to clipboard
"""
from __future__ import annotations

import json
import os
import select
import sys
import termios
import time
import tty
from pathlib import Path
from typing import Any

import click
import pyperclip
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from cli.config import ANALYSIS_OUTPUT_FORMAT

console = Console()


def _get_single_key() -> str:
    """Read a single key from stdin without waiting for Enter (raw mode)."""
    if not sys.stdin.isatty():
        return ""

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        # os.read bypasses Python's buffered IO — critical for escape sequences
        ch = os.read(fd, 1).decode("utf-8", errors="replace")

        if ch == '\x1b':
            seq = b''
            while select.select([sys.stdin], [], [], 0.1)[0]:
                seq += os.read(fd, 1)
            return ch + seq.decode("utf-8", errors="replace")
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _run_interactive_tui_v3(
    app_name: str,
    audit_results: dict[str, dict[str, Any]],
    row_limit: int = 20,
) -> None:
    """Interactive TUI with raw mode input and menu-driven filters."""
    all_items = _flatten_requirements(audit_results)
    chapters = sorted(set(i["chapter"] for i in all_items))
    components = sorted(set(i["component"] for i in all_items))
    severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    statuses = ["FAIL", "PASS", "N/A"]

    selected_indices: set[int] = set()
    cursor_pos = 0
    filters = {"component": [], "chapter": [], "severity": [], "status": [], "solve_status": [], "requirement": []}
    search_query = ""
    offset = 0

    def get_filtered_items():
        filtered = _flatten_requirements(
            audit_results,
            component_filter=filters.get("component") or None,
            chapter_filter=filters.get("chapter") or None,
            requirement_filter=filters.get("requirement") or None,
            severity_filter=filters.get("severity") or None,
            status_filter=filters.get("status") or None,
            solve_status_filter=filters.get("solve_status") or None,
        )
        if search_query:
            q = search_query.lower()
            filtered = [i for i in filtered if q in i.get("component", "").lower()
                      or q in i.get("chapter", "").lower()
                      or q in i.get("req", "").lower()
                      or q in i.get("title", "").lower()]
        return filtered

    def render(notify: str | None = None, notify_color: str = "green"):
        nonlocal cursor_pos, offset

        filtered = get_filtered_items()
        console.clear()
        console.print(f"[bold cyan]📋 Audit Results[/bold cyan] {app_name}")

        if not filtered:
            filter_parts = []
            for k, v in filters.items():
                if v:
                    if isinstance(v, list):
                        filter_parts.append(f"{k}={','.join(v)}")
                    else:
                        filter_parts.append(f"{k}={v}")
            filter_str = " | ".join(filter_parts) or "all"
            console.print(f"[dim]Filters: {filter_str}[/dim]")
            console.print("[yellow]No results match filters.[/yellow]")
            if notify:
                console.print(f"[{notify_color}]{notify}[/{notify_color}]")
            return

        total = len(filtered)
        total_failures = sum(1 for i in filtered if i["status"] == "FAIL")
        filter_parts = []
        for k, v in filters.items():
            if v:
                if isinstance(v, list):
                    filter_parts.append(f"{k}={','.join(v)}")
                else:
                    filter_parts.append(f"{k}={v}")
        filter_str = " | ".join(filter_parts) or "all"
        sel = len(selected_indices)

        if cursor_pos >= total:
            cursor_pos = total - 1
        if cursor_pos >= offset + row_limit:
            offset = cursor_pos - row_limit + 1
        if cursor_pos < offset:
            offset = cursor_pos

        console.print(f"[dim]Filters: {filter_str} | Search: {search_query or '(none)'}[/dim]")
        sel_color = "green" if sel else "dim"
        console.print(f"[dim]Selected: [{sel_color}]{sel}[/{sel_color}][dim] / {total}[/dim]  [dim]Failures: [red]{total_failures}[/red] / {total}[/dim]\n")

        table = Table(show_header=True, header_style="bold magenta", box=None)
        table.add_column("", width=3)
        table.add_column("", width=2)
        table.add_column("✓", width=2)
        table.add_column("Component", style="cyan", width=22)
        table.add_column("Ch", justify="center", width=4)
        table.add_column("Req", style="bold", width=8)
        table.add_column("Status", justify="center", width=8)
        table.add_column("Sev", justify="center", width=8)
        table.add_column("Solve", justify="center", width=10)
        table.add_column("Title", style="dim", max_width=28)

        for idx, item in enumerate(filtered[offset:offset + row_limit]):
            item_idx = offset + idx
            is_cursor   = item_idx == cursor_pos
            is_selected = item_idx in selected_indices
            is_solved   = item.get("solved_at")
            is_ignored  = item.get("ignored_at")
            is_tested   = item.get("tested_at")

            cursor_col = "[yellow]►[/yellow]" if is_cursor else "  "
            sel_col    = "[green]●[/green]"   if is_selected else " "
            if is_solved:
                solved_col = "[green]✓[/green]"
            elif is_tested:
                solved_col = "[blue]T[/blue]"
            elif is_ignored:
                solved_col = "[dim]~[/dim]"
            else:
                solved_col = " "

            sc = {"FAIL": "red", "PASS": "green", "N/A": "dim"}.get(item["status"], "white")
            vc = {"CRITICAL": "red bold", "HIGH": "yellow", "MEDIUM": "blue", "LOW": "green"}.get(item["severity"], "white")

            if is_solved:
                solve_status = "[green]Solved[/green]"
            elif is_tested:
                solve_status = "[blue]Tested[/blue]"
            elif is_ignored:
                solve_status = "[dim]Ignored[/dim]"
            else:
                solve_status = "[dim]Unsolved[/dim]"

            table.add_row(
                cursor_col, sel_col, solved_col,
                item["component"][:20],
                item["chapter"],
                item["req"],
                f"[{sc}]{item['status']}[/{sc}]",
                f"[{vc}]{item['severity']}[/{vc}]",
                solve_status,
                item["title"][:28],
            )

        console.print(table)
        console.print(f"\n[dim]Showing {offset+1}-{min(offset+row_limit, total)} of {total}[/dim]")

        if notify:
            console.print(f"[{notify_color}]{notify}[/{notify_color}]")
        else:
            console.print("[dim]SPC sel  s all  a fails  A clear  c copy  C copy+ctx  m solved  t tested  i ignore  ENTER detail  / search  f filter  r reset  R reload  q quit[/dim]")

    def _pick_menu(title: str, options: list[str], allow_text: bool = False) -> str | None:
        """Arrow-key navigable menu. Returns selected value or None (cancel)."""
        pos = 0

        while True:
            console.clear()
            console.print(f"[bold cyan]{title}[/bold cyan]\n")
            for i, opt in enumerate(options):
                marker = "[yellow]►[/yellow]" if i == pos else "  "
                console.print(f" {marker} {opt}")
            if allow_text:
                console.print(f"\n [dim]* Type manually[/dim]")
            console.print("\n[dim]↑↓ navigate | ENTER select | q cancel[/dim]")

            key = _get_single_key()

            if key in ('\x1b[A', '\x1bOA', 'k'):
                pos = max(0, pos - 1)
            elif key in ('\x1b[B', '\x1bOB', 'j'):
                pos = min(len(options) - 1, pos + 1)
            elif key in ('\r', '\n', ' '):
                return options[pos]
            elif key == '*' and allow_text:
                console.clear()
                console.print(f"[bold cyan]{title} — type value:[/bold cyan]")
                return input().strip() or None
            elif key == 'q' or key == '\x03':
                return None

    def _pick_multi_menu(title: str, options: list[str]) -> list[str]:
        """Multi-select menu with checkboxes. SPACE toggles, ENTER confirms."""
        selected = set()
        pos = 0

        while True:
            console.clear()
            console.print(f"[bold cyan]{title}[/bold cyan]\n")
            for i, opt in enumerate(options):
                marker = "[yellow]►[/yellow]" if i == pos else "  "
                box = "[green][x][/green]" if i in selected else "[ ]"
                console.print(f" {marker} {box} {opt}")
            console.print("\n[dim]↑↓ navigate | SPC toggle | ENTER confirm | q cancel[/dim]")

            key = _get_single_key()

            if key in ('\x1b[A', '\x1bOA', 'k'):
                pos = max(0, pos - 1)
            elif key in ('\x1b[B', '\x1bOB', 'j'):
                pos = min(len(options) - 1, pos + 1)
            elif key == ' ':
                if pos in selected:
                    selected.remove(pos)
                else:
                    selected.add(pos)
            elif key in ('\r', '\n'):
                return [options[i] for i in sorted(selected)]
            elif key == 'q' or key == '\x03':
                return []

    def show_filter_menu():
        nonlocal filters
        solve_statuses = ["solved", "unsolved", "ignored", "tested"]

        def build_filter_options():
            # Get requirements from current filtered view (respects all active filters except requirement/solve_status)
            temp_filters = {k: v for k, v in filters.items() if k not in ("requirement", "solve_status")}
            current_items = _flatten_requirements(
                audit_results,
                component_filter=temp_filters.get("component") or None,
                chapter_filter=temp_filters.get("chapter") or None,
                severity_filter=temp_filters.get("severity") or None,
                status_filter=temp_filters.get("status") or None,
            )
            requirements = sorted(set(i["req"] for i in current_items if i["req"]))
            return [
                ("component", "Component", components, True, True),
                ("chapter",   "Chapter",   chapters,   False, True),
                ("requirement", "Requirement ID", requirements, True, True),
                ("severity",  "Severity",  severities, False, True),
                ("status",    "Status",    statuses,   False, True),
                ("solve_status", "Solve Status", solve_statuses, False, True),
            ]

        pos = 0
        while True:
            filter_options = build_filter_options()
            menu_labels = []
            for key, label, _, _, _ in filter_options:
                val = filters[key]
                if isinstance(val, list):
                    display = f"{label}: [cyan]{','.join(val)}[/cyan]" if val else f"{label}: [dim]all[/dim]"
                else:
                    display = f"{label}: [cyan]{val}[/cyan]" if val else f"{label}: [dim]all[/dim]"
                menu_labels.append(display)
            menu_labels.append("[red]Reset all[/red]")

            console.clear()
            console.print("[bold cyan]📋 Filter Menu[/bold cyan]\n")
            for i, label in enumerate(menu_labels):
                marker = "[yellow]►[/yellow]" if i == pos else "  "
                console.print(f" {marker} {label}")
            console.print("\n[dim]↑↓ navigate | ENTER select | q cancel[/dim]")

            key = _get_single_key()

            if key in ('\x1b[A', '\x1bOA', 'k'):
                pos = max(0, pos - 1)
            elif key in ('\x1b[B', '\x1bOB', 'j'):
                pos = min(len(menu_labels) - 1, pos + 1)
            elif key in ('\r', '\n', ' '):
                if pos == len(filter_options):
                    filters = {"component": [], "chapter": [], "severity": [], "status": [], "solve_status": [], "requirement": []}
                    break
                fkey, _, opts, allow_text, is_multi = filter_options[pos]
                if is_multi:
                    val = _pick_multi_menu(f"Select {filter_options[pos][1]}", opts)
                    filters[fkey] = val
                else:
                    val = _pick_menu(f"Select {filter_options[pos][1]}", opts, allow_text)
                    if val is not None:
                        filters[fkey] = val
            elif key in ('q', '\x03'):
                break

    render()

    while True:
        filtered = get_filtered_items()

        key = _get_single_key()

        if key == "q":
            break
        elif key in ('\x1b[A', '\x1bOA', 'k'):
            if cursor_pos > 0:
                cursor_pos -= 1
            render()
        elif key in ('\x1b[B', '\x1bOB', 'j'):
            if cursor_pos < len(filtered) - 1:
                cursor_pos += 1
            render()
        elif key == " ":
            if cursor_pos in selected_indices:
                selected_indices.remove(cursor_pos)
            else:
                selected_indices.add(cursor_pos)
            render()
        elif key == "/":
            console.clear()
            console.print("[bold cyan]Search:[/bold cyan]")
            search_query = input().strip()
            cursor_pos = 0
            offset = 0
            render()
        elif key == "s":
            # Select all items currently visible after filters/search
            selected_indices = set(range(len(filtered)))
            render()
        elif key == "a":
            # Select only failures in current filtered view
            selected_indices = set(i for i, item in enumerate(filtered) if item["status"] == "FAIL")
            render()
        elif key == "A":
            selected_indices.clear()
            render()
        elif key in ("c", "C"):
            if selected_indices:
                items = [filtered[i] for i in sorted(selected_indices) if i < len(filtered)]
            else:
                items = [filtered[cursor_pos]] if cursor_pos < len(filtered) else []
            if items:
                with_ctx = key == "C"
                result = _copy_items_to_clipboard(items, app_name=app_name, include_context=with_ctx)
                if result:
                    item_count, ctx_count = result
                    if with_ctx:
                        msg = f"✓ Copied {item_count} item(s) + {ctx_count} context file(s)"
                    else:
                        msg = f"✓ Copied {item_count} item(s) to clipboard"
                    render(notify=msg)
                    time.sleep(1)
            render()
        elif key == "r":
            filters = {"component": [], "chapter": [], "severity": [], "status": [], "solve_status": [], "requirement": []}
            search_query = ""
            cursor_pos = 0
            offset = 0
            render()
        elif key == "R":
            new_results = _scan_audit_results(app_name)
            audit_results.clear()
            audit_results.update(new_results)
            render(notify="✓ Reloaded data from disk")
        elif key == "f":
            show_filter_menu()
            cursor_pos = 0
            offset = 0
            render()

        elif key == "m":
            items_to_mark = []
            if selected_indices:
                items_to_mark = [filtered[i] for i in sorted(selected_indices) if i < len(filtered)]
            elif cursor_pos < len(filtered):
                items_to_mark = [filtered[cursor_pos]]

            if items_to_mark:
                console.clear()
                console.print("[bold cyan]Mark as Solved[/bold cyan]\n")
                console.print(f"Marking {len(items_to_mark)} item(s)\n")
                commit = input("[dim]Commit hash (optional):[/dim] ").strip()
                comment = input("[dim]Comment (optional):[/dim] ").strip()

                success_count = 0
                for item in items_to_mark:
                    success = _mark_item_as_solved(
                        app_name,
                        item["component"],
                        item["chapter"],
                        item["req"],
                        item["title"],
                        commit if commit else None,
                        comment if comment else None
                    )
                    if success:
                        success_count += 1
                        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        # Update item in memory
                        item["solved_at"] = timestamp
                        if commit:
                            item["solved_commit"] = commit
                        if comment:
                            item["solved_comment"] = comment
                        # Update audit_results in-memory dict
                        if item["component"] in audit_results and item["chapter"] in audit_results[item["component"]]:
                            for req in audit_results[item["component"]][item["chapter"]]:
                                if req.get("req") == item["req"] and req.get("tit", "") == item["title"]:
                                    req["solved_at"] = timestamp
                                    if commit:
                                        req["solved_commit"] = commit
                                    if comment:
                                        req["solved_comment"] = comment
                                    break

                selected_indices.clear()
                render(notify=f"✓ Marked {success_count}/{len(items_to_mark)} as solved")
                time.sleep(1)
            render()

        elif key == "i":
            items_to_mark = []
            if selected_indices:
                items_to_mark = [filtered[i] for i in sorted(selected_indices) if i < len(filtered)]
            elif cursor_pos < len(filtered):
                items_to_mark = [filtered[cursor_pos]]

            if items_to_mark:
                console.clear()
                console.print("[bold cyan]Mark as Ignored[/bold cyan]\n")
                console.print(f"Marking {len(items_to_mark)} item(s)\n")
                comment = input("[dim]Comment (optional):[/dim] ").strip()

                success_count = 0
                for item in items_to_mark:
                    success = _mark_item_as_ignored(
                        app_name,
                        item["component"],
                        item["chapter"],
                        item["req"],
                        item["title"],
                        comment if comment else None
                    )
                    if success:
                        success_count += 1
                        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        # Update item in memory
                        item["ignored_at"] = timestamp
                        if comment:
                            item["ignored_comment"] = comment
                        # Update audit_results in-memory dict
                        if item["component"] in audit_results and item["chapter"] in audit_results[item["component"]]:
                            for req in audit_results[item["component"]][item["chapter"]]:
                                if req.get("req") == item["req"] and req.get("tit", "") == item["title"]:
                                    req["ignored_at"] = timestamp
                                    if comment:
                                        req["ignored_comment"] = comment
                                    break

                selected_indices.clear()
                render(notify=f"✓ Marked {success_count}/{len(items_to_mark)} as ignored")
                time.sleep(1)
            render()

        elif key == "t":
            items_to_mark = []
            if selected_indices:
                items_to_mark = [filtered[i] for i in sorted(selected_indices) if i < len(filtered)]
            elif cursor_pos < len(filtered):
                items_to_mark = [filtered[cursor_pos]]

            if items_to_mark:
                console.clear()
                console.print("[bold cyan]Mark as Tested[/bold cyan]\n")
                console.print(f"Marking {len(items_to_mark)} item(s)\n")
                comment = input("[dim]Comment (optional):[/dim] ").strip()

                success_count = 0
                for item in items_to_mark:
                    success = _mark_item_as_tested(
                        app_name,
                        item["component"],
                        item["chapter"],
                        item["req"],
                        item["title"],
                        comment if comment else None
                    )
                    if success:
                        success_count += 1
                        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        # Update item in memory
                        item["tested_at"] = timestamp
                        if comment:
                            item["tested_comment"] = comment
                        # Update audit_results in-memory dict
                        if item["component"] in audit_results and item["chapter"] in audit_results[item["component"]]:
                            for req in audit_results[item["component"]][item["chapter"]]:
                                if req.get("req") == item["req"] and req.get("tit", "") == item["title"]:
                                    req["tested_at"] = timestamp
                                    if comment:
                                        req["tested_comment"] = comment
                                    break

                selected_indices.clear()
                render(notify=f"✓ Marked {success_count}/{len(items_to_mark)} as tested")
                time.sleep(1)
            render()

        elif key in ("d", "\r", "\n"):
            if cursor_pos < len(filtered):
                item = filtered[cursor_pos]
                console.clear()
                console.print(_render_detail_panel(item))
                console.print("\n[dim]Press any key to continue...[/dim]")
                _get_single_key()
            render()


def _scan_audit_results(app_name: str) -> dict[str, dict[str, Any]]:
    """Scan all audit result files and return structured data."""
    components_dir = Path(f"outputs/{app_name}/components")
    if not components_dir.exists():
        return {}

    results = {}
    target_format = ANALYSIS_OUTPUT_FORMAT if ANALYSIS_OUTPUT_FORMAT in ("json", "xml") else "json"

    for comp_dir in components_dir.iterdir():
        if not comp_dir.is_dir() or comp_dir.name in ["README.md", "index.json"]:
            continue

        comp_id = comp_dir.name
        results[comp_id] = {}

        analysis_dir = comp_dir / "analysis"
        if not analysis_dir.exists():
            continue

        for analysis_file in analysis_dir.iterdir():
            if not analysis_file.is_file():
                continue

            file_ext = analysis_file.suffix.lower()
            if file_ext != f".{target_format}":
                continue

            chapter = analysis_file.stem
            try:
                if target_format == "xml":
                    import xml.etree.ElementTree as ET

                    root = ET.parse(analysis_file).getroot()
                    reqs = root.findall("requirements/requirement")
                    items = []
                    for r in reqs:
                        items.append({
                            "req": r.get("id", ""),
                            "status": r.get("status", ""),
                            "sev": r.get("severity", ""),
                            "tit": r.findtext("title", ""),
                            "desc": r.findtext("description", ""),
                        })
                else:
                    with analysis_file.open(encoding="utf-8") as f:
                        data = json.load(f)
                    items = data.get("results", [])

                results[comp_id][chapter] = items
            except Exception:
                continue

    return results


def _flatten_requirements(
    audit_results: dict[str, dict[str, Any]],
    component_filter: list[str] | None = None,
    chapter_filter: list[str] | None = None,
    requirement_filter: list[str] | None = None,
    status_filter: list[str] | None = None,
    severity_filter: list[str] | None = None,
    solve_status_filter: list[str] | None = None,
) -> list[dict]:
    """Flatten and filter all requirements across components/chapters. Filters use OR logic (union)."""
    items = []

    for comp_id, chapters in audit_results.items():
        if component_filter and comp_id not in component_filter:
            continue

        for chapter, reqs in chapters.items():
            if chapter_filter and chapter not in chapter_filter:
                continue

            for req in reqs:
                req_id = req.get("req", "")
                if requirement_filter and not any(req_id.startswith(r) for r in requirement_filter):
                    continue

                req_status = req.get("status", "")
                if status_filter and req_status.upper() not in [s.upper() for s in status_filter]:
                    continue

                req_severity = req.get("sev", "")
                if severity_filter and req_severity.upper() not in [s.upper() for s in severity_filter]:
                    continue

                item = {
                    "component": comp_id,
                    "chapter": chapter,
                    "req": req_id,
                    "status": req_status,
                    "severity": req_severity,
                    "title": req.get("tit", ""),
                    "description": req.get("desc", ""),
                    "locations": req.get("locations", []),
                    "hint": req.get("hint", ""),
                    "solved_at": req.get("solved_at"),
                    "solved_commit": req.get("solved_commit"),
                    "solved_comment": req.get("solved_comment"),
                    "ignored_at": req.get("ignored_at"),
                    "ignored_comment": req.get("ignored_comment"),
                    "tested_at": req.get("tested_at"),
                    "tested_comment": req.get("tested_comment"),
                }

                # Filter by solve status
                if solve_status_filter:
                    has_solved = "solved_at" in req and req["solved_at"]
                    has_ignored = "ignored_at" in req and req["ignored_at"]
                    has_tested = "tested_at" in req and req["tested_at"]
                    item_solve_status = "solved" if has_solved else "tested" if has_tested else "ignored" if has_ignored else "unsolved"
                    if item_solve_status not in solve_status_filter:
                        continue

                items.append(item)

    return items


def _render_detail_panel(item: dict) -> Panel:
    """Render detailed view of a single item."""
    status_color = {
        "FAIL": "red",
        "PASS": "green",
        "N/A": "dim",
    }.get(item["status"], "white")

    content = f"""
[bold cyan]Component:[/bold cyan] {item['component']}
[bold cyan]Chapter:[/bold cyan] {item['chapter']}
[bold cyan]Requirement:[/bold cyan] {item['req']}
[bold cyan]Status:[/bold cyan] [{status_color}]{item['status']}[/{status_color}]
[bold cyan]Severity:[/bold cyan] {item['severity']}

[bold cyan]Title:[/bold cyan]
{item['title']}

[bold cyan]Description:[/bold cyan]
{item['description']}

[bold cyan]Hint:[/bold cyan]
{item.get('hint', 'N/A')}

[bold cyan]Locations:[/bold cyan]
"""
    for loc in item.get("locations", []):
        file_path = loc.get("file", "N/A")
        func = loc.get("func", "")
        lines = loc.get("lines", [])
        content += f"  {file_path}"
        if func:
            content += f" :: {func}"
        if lines:
            content += f" (lines: {', '.join(map(str, lines))})"
        content += "\n"

    return Panel(content.strip(), title=f"Detail: {item['req']}", border_style="cyan")


def _mark_item_as_solved(app_name: str, component_id: str, chapter: str, req_id: str, title: str, commit: str | None = None, comment: str | None = None) -> bool:
    """Mark a requirement as solved in the analysis JSON file. Returns True if successful."""
    path = Path(f"outputs/{app_name}/components/{component_id}/analysis/{chapter}.json")
    if not path.exists():
        return False

    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        results = data.get("results", [])
        for item in results:
            if item.get("req") == req_id and item.get("tit", "") == title:
                item["solved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                if commit:
                    item["solved_commit"] = commit.strip()
                if comment:
                    item["solved_comment"] = comment.strip()
                path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                return True
        return False
    except Exception:
        return False


def _mark_item_as_ignored(app_name: str, component_id: str, chapter: str, req_id: str, title: str, comment: str | None = None) -> bool:
    """Mark a requirement as ignored in the analysis JSON file. Returns True if successful."""
    path = Path(f"outputs/{app_name}/components/{component_id}/analysis/{chapter}.json")
    if not path.exists():
        return False

    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        results = data.get("results", [])
        for item in results:
            if item.get("req") == req_id and item.get("tit", "") == title:
                item["ignored_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                if comment:
                    item["ignored_comment"] = comment.strip()
                path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                return True
        return False
    except Exception:
        return False


def _mark_item_as_tested(app_name: str, component_id: str, chapter: str, req_id: str, title: str, comment: str | None = None) -> bool:
    """Mark a requirement as tested in the analysis JSON file. Returns True if successful."""
    path = Path(f"outputs/{app_name}/components/{component_id}/analysis/{chapter}.json")
    if not path.exists():
        return False

    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        results = data.get("results", [])
        for item in results:
            if item.get("req") == req_id and item.get("tit", "") == title:
                item["tested_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                if comment:
                    item["tested_comment"] = comment.strip()
                path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                return True
        return False
    except Exception:
        return False


def _read_component_context(app_name: str, component_id: str) -> str | None:
    """Read context.yml (or .yaml, .xml) for a component, return raw text or None if missing."""
    base_path = Path(f"outputs/{app_name}/components/{component_id}")
    for filename in ["context.yml", "context.yaml", "context.xml"]:
        path = base_path / filename
        if path.exists():
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
    return None


def _copy_items_to_clipboard(
    items: list[dict],
    app_name: str | None = None,
    include_context: bool = False,
) -> tuple[int, int] | None:
    """Copy items to clipboard as structured AI-prompt-ready text.

    When include_context=True and app_name is provided, context files
    of each unique component are prepended so the AI has full source context.

    Returns: (total_items, contexts_found) or None if failed to copy.
    """
    if not items:
        return None

    lines: list[str] = []
    lines.append(f"# Security Audit Findings ({len(items)} item{'s' if len(items) != 1 else ''})\n")

    # Prepend component contexts when requested
    contexts_found = 0
    if include_context and app_name:
        seen_components: set[str] = set()
        for item in items:
            comp = item.get("component", "")
            if comp and comp not in seen_components:
                seen_components.add(comp)
                ctx = _read_component_context(app_name, comp)
                if ctx:
                    contexts_found += 1
                    lines.append(f"## Component Context: {comp}")
                    lines.append("```yaml")
                    lines.append(ctx.strip())
                    lines.append("```\n")
                    lines.append("---\n")

    for item in items:
        sev = item.get("severity", "")
        status = item.get("status", "")
        req = item.get("req", "")
        lines.append(f"## [{status}] {req} — {item.get('title', '')}")
        lines.append(f"- Component : {item.get('component', '')}")
        lines.append(f"- Chapter   : {item.get('chapter', '')}")
        lines.append(f"- Severity  : {sev}")
        lines.append(f"- Status    : {status}")

        desc = item.get("description", "").strip()
        if desc:
            lines.append(f"\n**Description:**\n{desc}")

        hint = item.get("hint", "").strip()
        if hint:
            lines.append(f"\n**Hint / Recommendation:**\n{hint}")

        locations = item.get("locations", [])
        if locations:
            lines.append("\n**Locations:**")
            for loc in locations:
                loc_line = f"- {loc.get('file', '')}"
                if loc.get("func"):
                    loc_line += f" :: {loc['func']}"
                if loc.get("lines"):
                    loc_line += f" (lines: {', '.join(map(str, loc['lines']))})"
                lines.append(loc_line)

        lines.append("\n---\n")

    output = "\n".join(lines)
    try:
        pyperclip.copy(output)
        return (len(items), contexts_found)
    except Exception:
        return None


@click.command("list")
@click.argument("app_name")
@click.option("--failures-only", is_flag=True, help="Show only FAILED requirements.")
@click.option("--component", "component_filter", default=None, help="Filter by component ID.")
@click.option("--chapter", "chapter_filter", default=None, help="Filter by chapter (e.g. V1).")
@click.option("--requirement", "requirement_filter", default=None, help="Filter by requirement ID.")
@click.option("--status", "status_filter", default=None, help="Filter by status (FAIL, PASS, N/A).")
@click.option("--severity", "severity_filter", default=None, help="Filter by severity (HIGH, MEDIUM, LOW).")
@click.option("--copy", "copy_mode", is_flag=True, help="Copy results to clipboard.")
@click.option("--format", "format_mode", type=str, default="summary", help="Output format.")
@click.option("--interactive", "-i", is_flag=True, help="Interactive TUI mode (default when no filters).")
@click.option("--limit", "-n", "row_limit", type=int, default=None, help="Limit number of rows to display.")
def list_cmd(
    app_name: str,
    failures_only: bool,
    component_filter: str | None,
    chapter_filter: str | None,
    requirement_filter: str | None,
    status_filter: str | None,
    severity_filter: str | None,
    copy_mode: bool,
    format_mode: str,
    interactive: bool,
    row_limit: int | None,
) -> None:
    """List and filter audit results."""
    console.print(f"[bold cyan]📋 Audit Results[/bold cyan] {app_name}")

    audit_results = _scan_audit_results(app_name)
    if not audit_results:
        console.print("[red]No audit results found. Run audit first.[/red]")
        return

    has_filters = any([
        failures_only, component_filter, chapter_filter, requirement_filter,
        status_filter, severity_filter, copy_mode, format_mode != "summary"
    ])

    if interactive or not has_filters:
        _run_interactive_tui_v3(app_name, audit_results, row_limit or 20)
        return

    status = status_filter if status_filter else ("FAIL" if failures_only else None)

    items = _flatten_requirements(
        audit_results,
        component_filter=component_filter,
        chapter_filter=chapter_filter,
        requirement_filter=requirement_filter,
        status_filter=status,
        severity_filter=severity_filter,
    )

    if format_mode == "json":
        console.print(json.dumps(items, indent=2, ensure_ascii=False))
    else:
        _display_summary_table(items)

    if copy_mode:
        _copy_items_to_clipboard(items)

    console.print(f"\n[dim]Found {len(items)} requirements[/dim]")


def _display_summary_table(items: list[dict]) -> None:
    """Display summary table."""
    if not items:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Component", style="cyan", width=28)
    table.add_column("Ch", justify="center", width=4)
    table.add_column("Req", style="bold", width=8)
    table.add_column("Status", justify="center", width=8)
    table.add_column("Sev", justify="center", width=8)
    table.add_column("Title", style="dim", max_width=40)

    for item in items:
        status_color = {"FAIL": "red", "PASS": "green", "N/A": "dim"}.get(item["status"], "white")
        severity_color = {"CRITICAL": "red", "HIGH": "yellow", "MEDIUM": "blue", "LOW": "green"}.get(item["severity"], "white")

        table.add_row(
            item["component"][:28],
            item["chapter"],
            item["req"],
            f"[{status_color}]{item['status']}[/{status_color}]",
            f"[{severity_color}]{item['severity']}[/{severity_color}]",
            item["title"][:40],
        )

    console.print(table)
