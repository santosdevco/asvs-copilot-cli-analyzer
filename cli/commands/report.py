"""
commands/report.py
──────────────────
Generates a Markdown report for one application using:
- Per-app execution log (outputs/<app>/log_app.log)
- Usage reports (outputs/<app>/usage/*_usage.json)
- Audit analysis files (outputs/<app>/components/*/analysis/*.json)

Usage:
  python cli.py report <app_name>
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.prompt import Confirm, Prompt

from cli.config import OUTPUTS_DIR
from cli.core import load_component_index
from cli.core.app_logger import init_app_logger, log_event

console = Console()


_SESSION_RE = re.compile(r"SESSION START\n(\{[\s\S]*?\n\})", re.MULTILINE)
_BLOCK_RE = re.compile(
    r"--- ([A-Z0-9_]+) START \[([^\]]+)\] ---\n([\s\S]*?)\n--- \1 END ---",
    re.MULTILINE,
)


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_usage_reports(app_name: str) -> list[dict[str, Any]]:
    usage_dir = OUTPUTS_DIR / app_name / "usage"
    if not usage_dir.exists():
        return []

    reports: list[dict[str, Any]] = []
    for p in sorted(usage_dir.glob("*_usage.json")):
        # Skip rolling aliases to avoid double counting.
        if p.name.startswith("latest_"):
            continue
        data = _safe_read_json(p)
        if not data:
            continue
        data["_file"] = str(p)
        reports.append(data)

    def _sort_key(item: dict[str, Any]) -> str:
        return str(item.get("generated_at") or "")

    return sorted(reports, key=_sort_key)


def _aggregate_usage(reports: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "input_tokens": 0.0,
        "output_tokens": 0.0,
        "cache_read_tokens": 0.0,
        "cache_write_tokens": 0.0,
        "reasoning_tokens": 0.0,
        "cost": 0.0,
        "duration_seconds": 0.0,
        "assistant_usage_events": 0,
        "total_tokens": 0.0,
    }
    by_command: dict[str, float] = defaultdict(float)

    def _coerce_duration_seconds(raw_value: float | int | None) -> float:
        value = float(raw_value or 0.0)
        # Backward compatibility: older usage files stored milliseconds.
        if value > 10_000:
            return value / 1000.0
        return value

    for report in reports:
        t = report.get("totals") or {}
        totals["input_tokens"] += float(t.get("input_tokens") or 0.0)
        totals["output_tokens"] += float(t.get("output_tokens") or 0.0)
        totals["cache_read_tokens"] += float(t.get("cache_read_tokens") or 0.0)
        totals["cache_write_tokens"] += float(t.get("cache_write_tokens") or 0.0)
        totals["reasoning_tokens"] += float(t.get("reasoning_tokens") or 0.0)
        totals["cost"] += float(t.get("cost") or 0.0)
        totals["duration_seconds"] += _coerce_duration_seconds(t.get("duration_seconds"))
        totals["assistant_usage_events"] += int(t.get("assistant_usage_events") or 0)
        totals["total_tokens"] += float(t.get("total_tokens") or 0.0)

        cmd = str(report.get("command") or "unknown")
        by_command[cmd] += float(t.get("total_tokens") or 0.0)

    return {"totals": totals, "by_command": dict(by_command)}


def _load_log_sections(app_name: str) -> dict[str, Any]:
    log_file = OUTPUTS_DIR / app_name / "log_app.log"
    if not log_file.exists():
        return {
            "path": str(log_file),
            "exists": False,
            "sessions": [],
            "events": [],
            "blocks": [],
        }

    text = log_file.read_text(encoding="utf-8")

    sessions: list[dict[str, Any]] = []
    for m in _SESSION_RE.finditer(text):
        try:
            sessions.append(json.loads(m.group(1)))
        except Exception:
            continue

    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if "event" in obj and "timestamp" in obj:
            events.append(obj)

    blocks: list[dict[str, Any]] = []
    for label, ts, content in _BLOCK_RE.findall(text):
        blocks.append({"label": label, "timestamp": ts, "content": content})

    return {
        "path": str(log_file),
        "exists": True,
        "sessions": sessions,
        "events": events,
        "blocks": blocks,
    }


def _load_audit_summary(app_name: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "components": [],
        "total_fail": 0,
        "total_pass": 0,
        "total_na": 0,
    }

    try:
        index = load_component_index(app_name)
        components = index.project_triage
    except Exception:
        components = []

    for comp in components:
        analysis_dir = OUTPUTS_DIR / app_name / "components" / comp.component_id / "analysis"
        chapter_rows: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []

        if analysis_dir.exists():
            for p in sorted(analysis_dir.glob("V*.json")):
                data = _safe_read_json(p)
                if not data:
                    continue
                results = data.get("audit_results") or []
                fail = 0
                passed = 0
                na = 0
                for item in results:
                    status = str(item.get("status") or "").upper()
                    if status == "FAIL":
                        fail += 1
                        findings.append(
                            {
                                "chapter": p.stem,
                                "requirement_id": item.get("requirement_id"),
                                "severity": item.get("severity"),
                                "title": item.get("vulnerability_title") or item.get("description"),
                                "affected_file": item.get("affected_file"),
                                "affected_function": item.get("affected_function"),
                            }
                        )
                    elif status == "PASS":
                        passed += 1
                    elif status == "NOT_APPLICABLE":
                        na += 1

                summary["total_fail"] += fail
                summary["total_pass"] += passed
                summary["total_na"] += na
                chapter_rows.append(
                    {
                        "chapter": p.stem,
                        "fail": fail,
                        "pass": passed,
                        "na": na,
                        "checks": len(results),
                    }
                )

        summary["components"].append(
            {
                "component_id": comp.component_id,
                "component_name": comp.component_name,
                "risk_level": comp.risk_level,
                "asset_tags": list(comp.asset_tags),
                "chapters": chapter_rows,
                "findings": findings,
            }
        )

    return summary


def _interactive_report_options() -> dict[str, Any]:
    console.print("\n[bold cyan]Report options menu[/bold cyan]")
    include_sessions = Confirm.ask("Include command sessions from log?", default=True)
    include_events = Confirm.ask("Include event timeline from log?", default=True)
    include_prompts = Confirm.ask("Include input prompts? (can be long)", default=True)
    include_outputs = Confirm.ask("Include chat/LLM outputs? (can be long)", default=True)
    include_audit = Confirm.ask("Include audit summary by component/chapter?", default=True)
    include_usage_files = Confirm.ask("Include per-usage file token table?", default=True)

    max_events = int(Prompt.ask("Max events to include", default="200"))
    max_block_chars = int(Prompt.ask("Max chars per prompt/output block", default="4000"))

    return {
        "include_sessions": include_sessions,
        "include_events": include_events,
        "include_prompts": include_prompts,
        "include_outputs": include_outputs,
        "include_audit_summary": include_audit,
        "include_usage_files": include_usage_files,
        "max_events": max_events,
        "max_block_chars": max_block_chars,
    }


def _default_report_options() -> dict[str, Any]:
    return {
        "include_sessions": True,
        "include_events": True,
        "include_prompts": True,
        "include_outputs": True,
        "include_audit_summary": True,
        "include_usage_files": True,
        "max_events": 200,
        "max_block_chars": 4000,
    }


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[TRUNCATED]"


_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4, "": 5}


def _severity_badge(sev: str | None) -> str:
    sev = (sev or "").upper()
    mapping = {
        "CRITICAL": "🔴",
        "HIGH": "🟠",
        "MEDIUM": "🟡",
        "LOW": "🔵",
        "INFO": "⚪",
    }
    return mapping.get(sev, "⚪")


def _render_markdown(
    app_name: str,
    options: dict[str, Any],
    usage_reports: list[dict[str, Any]],
    usage_agg: dict[str, Any],
    log_data: dict[str, Any],
    audit_summary: dict[str, Any],
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────────────────────
    lines += [
        f"# Security Audit Report — {app_name}",
        "",
        f"> Generated: {now}",
        "",
        "---",
        "",
    ]

    # ── 1. Components identified ─────────────────────────────────────────────
    components = audit_summary.get("components") or []
    lines += [
        "## 1. Components Identified",
        "",
        f"| # | Component | Risk Level | Asset Tags | Chapters Analyzed |",
        f"|---|-----------|:----------:|------------|:-----------------:|",
    ]
    for i, comp in enumerate(components, 1):
        comp_id = comp.get("component_id") or ""
        comp_name = comp.get("component_name") or comp_id
        risk = comp.get("risk_level") or ""
        risk_colors = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}
        risk_badge = risk_colors.get(risk.upper(), "") + " " + risk
        tags = ", ".join(comp.get("asset_tags") or [])
        chapters = comp.get("chapters") or []
        n_chapters = len(chapters)
        lines.append(f"| {i} | **{comp_name}** | {risk_badge} | {tags} | {n_chapters} |")
    lines += ["", ""]

    # ── 2. ASVS audit results by component ───────────────────────────────────
    if options.get("include_audit_summary"):
        tf = audit_summary.get("total_fail", 0)
        tp = audit_summary.get("total_pass", 0)
        tna = audit_summary.get("total_na", 0)
        total_checks = tf + tp + tna
        pass_rate = (tp / total_checks * 100) if total_checks else 0.0

        lines += [
            "## 2. ASVS Audit Results",
            "",
            "### Overall summary",
            "",
            "| Metric | Value |",
            "|--------|------:|",
            f"| ✅ PASS | {tp} |",
            f"| ❌ FAIL | {tf} |",
            f"| ⬜ N/A | {tna} |",
            f"| Total checks | {total_checks} |",
            f"| Pass rate | {pass_rate:.1f}% |",
            "",
        ]

        for comp in components:
            comp_id = comp.get("component_id") or ""
            comp_name = comp.get("component_name") or comp_id
            risk = comp.get("risk_level") or ""
            chapters = comp.get("chapters") or []
            findings = comp.get("findings") or []

            comp_fail = sum(c.get("fail", 0) for c in chapters)
            comp_pass = sum(c.get("pass", 0) for c in chapters)
            comp_na = sum(c.get("na", 0) for c in chapters)
            comp_checks = comp_fail + comp_pass + comp_na
            comp_pass_rate = (comp_pass / comp_checks * 100) if comp_checks else 0.0

            lines += [
                f"### {comp_name}",
                "",
                f"- **component_id**: `{comp_id}`",
                f"- **risk_level**: {risk}",
                f"- **checks**: {comp_checks}  ✅ {comp_pass}  ❌ {comp_fail}  ⬜ {comp_na}"
                f"  (pass rate: {comp_pass_rate:.1f}%)",
                "",
            ]

            if chapters:
                lines += [
                    "**Chapter breakdown:**",
                    "",
                    "| Chapter | Checks | PASS | FAIL | N/A |",
                    "|---------|-------:|-----:|-----:|----:|",
                ]
                for ch in chapters:
                    lines.append(
                        f"| {ch.get('chapter')} | {ch.get('checks')} | "
                        f"{ch.get('pass')} | {ch.get('fail')} | {ch.get('na')} |"
                    )
                lines.append("")

            if findings:
                # sort by severity
                sorted_findings = sorted(
                    findings,
                    key=lambda x: _SEVERITY_ORDER.get(str(x.get("severity") or "").upper(), 5),
                )
                lines += [
                    "**Vulnerabilities found:**",
                    "",
                    "| Sev | Chapter | Req ID | Title | File | Function |",
                    "|----|---------|--------|-------|------|----------|",
                ]
                for f in sorted_findings:
                    badge = _severity_badge(f.get("severity"))
                    sev = (f.get("severity") or "").upper()
                    ch = f.get("chapter") or ""
                    req = f.get("requirement_id") or ""
                    title = (str(f.get("title") or "")[:70]).replace("|", "\\|")
                    afile = (f.get("affected_file") or "").replace("|", "\\|")
                    afunc = (f.get("affected_function") or "").replace("|", "\\|")
                    lines.append(f"| {badge} {sev} | {ch} | {req} | {title} | {afile} | {afunc} |")
                lines.append("")
            elif chapters:
                lines += ["*No FAIL findings in this component.*", ""]

            lines.append("")

    # ── 3. Command sessions (optional) ──────────────────────────────────────
    if options.get("include_sessions"):
        sessions = log_data.get("sessions") or []
        lines += [
            "## 3. Command Sessions",
            "",
            "| Timestamp | Command | Command Line |",
            "|-----------|---------|--------------|",
        ]
        if not sessions:
            lines.append("| — | No sessions found | |")
        else:
            for s in sessions:
                ts = s.get("timestamp") or ""
                cmd = s.get("command") or ""
                cli_line = (s.get("command_line") or "").replace("|", "\\|")
                lines.append(f"| {ts} | `{cmd}` | `{cli_line}` |")
        lines += ["", ""]

    # ── 4. Event timeline (optional) ────────────────────────────────────────
    if options.get("include_events"):
        events = (log_data.get("events") or [])[-int(options.get("max_events") or 200):]
        lines += [
            "## 4. Event Timeline",
            "",
            "| Timestamp | Event | Data |",
            "|-----------|-------|------|",
        ]
        if not events:
            lines.append("| — | No events found | |")
        else:
            for e in events:
                ts = e.get("timestamp") or ""
                ev = e.get("event") or ""
                data_str = json.dumps(e.get("data"), ensure_ascii=False).replace("|", "\\|")[:200]
                lines.append(f"| {ts} | `{ev}` | {data_str} |")
        lines += ["", ""]

    # ── 5. Prompts / outputs (optional) ────────────────────────────────────
    include_prompts = bool(options.get("include_prompts"))
    include_outputs = bool(options.get("include_outputs"))
    max_block_chars = int(options.get("max_block_chars") or 4000)

    if include_prompts or include_outputs:
        blocks = log_data.get("blocks") or []
        filtered: list[dict[str, Any]] = []
        for b in blocks:
            label = str(b.get("label") or "")
            is_prompt = "PROMPT" in label
            is_output = "OUTPUT" in label
            if (is_prompt and include_prompts) or (is_output and include_outputs):
                filtered.append(b)

        lines += ["## 5. Prompt and Output Blocks", ""]
        if not filtered:
            lines += ["*No matching blocks found.*", ""]
        else:
            for b in filtered:
                label = b.get("label")
                bts = b.get("timestamp")
                content = _truncate(str(b.get("content") or ""), max_block_chars)
                lines += [f"### {label} ({bts})", "", "```text", content, "```", ""]

    # ── 6. Token consumption (ALWAYS LAST) ──────────────────────────────────
    totals = usage_agg.get("totals") or {}
    by_command = usage_agg.get("by_command") or {}

    lines += [
        "---",
        "",
        "## Token Consumption Summary",
        "",
        "### Totals across all runs",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Input tokens | {float(totals.get('input_tokens') or 0.0):.0f} |",
        f"| Output tokens | {float(totals.get('output_tokens') or 0.0):.0f} |",
        f"| Cache read tokens | {float(totals.get('cache_read_tokens') or 0.0):.0f} |",
        f"| Cache write tokens | {float(totals.get('cache_write_tokens') or 0.0):.0f} |",
        f"| Reasoning tokens | {float(totals.get('reasoning_tokens') or 0.0):.0f} |",
        f"| **Total tokens** | **{float(totals.get('total_tokens') or 0.0):.0f}** |",
        f"| Assistant usage events | {int(totals.get('assistant_usage_events') or 0)} |",
        f"| Duration (s, sum) | {float(totals.get('duration_seconds') or 0.0):.0f} |",
        f"| Estimated cost (sum) | {float(totals.get('cost') or 0.0):.4f} |",
        "",
    ]

    if by_command:
        lines += [
            "### Tokens by command",
            "",
            "| Command | Tokens |",
            "|---------|-------:|",
        ]
        for cmd, val in sorted(by_command.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"| {cmd} | {val:.0f} |")
        lines.append("")

    if options.get("include_usage_files") and usage_reports:
        lines += [
            "### Per-execution usage files",
            "",
            "| Generated At | Command | Calls | Total Tokens |",
            "|-------------|---------|------:|-------------:|",
        ]
        for r in usage_reports:
            t = r.get("totals") or {}
            lines.append(
                f"| {r.get('generated_at')} | {r.get('command')} "
                f"| {r.get('calls_count')} | {float(t.get('total_tokens') or 0.0):.0f} |"
            )
        lines.append("")

    lines += [
        "---",
        "",
        f"> **Grand total tokens consumed: {float(totals.get('total_tokens') or 0.0):.0f}**",
        "",
    ]

    return "\n".join(lines).strip() + "\n"


@click.command("report")
@click.argument("app_name")
@click.option("--interactive-menu/--no-interactive-menu", default=True, show_default=True, help="Show interactive menu to choose report sections.")
@click.option("--include-sessions/--no-include-sessions", default=True, show_default=True, help="Include command sessions section.")
@click.option("--include-events/--no-include-events", default=True, show_default=True, help="Include event timeline section.")
@click.option("--include-prompts/--no-include-prompts", default=True, show_default=True, help="Include prompt blocks section.")
@click.option("--include-outputs/--no-include-outputs", default=True, show_default=True, help="Include output blocks section.")
@click.option("--include-audit-summary/--no-include-audit-summary", default=True, show_default=True, help="Include ASVS audit summary section.")
@click.option("--include-usage-files/--no-include-usage-files", default=True, show_default=True, help="Include per-execution usage table.")
@click.option("--max-events", default=200, show_default=True, type=int, help="Max events to include in Event Timeline.")
@click.option("--max-block-chars", default=4000, show_default=True, type=int, help="Max chars per prompt/output block.")
def report_cmd(
    app_name: str,
    interactive_menu: bool,
    include_sessions: bool,
    include_events: bool,
    include_prompts: bool,
    include_outputs: bool,
    include_audit_summary: bool,
    include_usage_files: bool,
    max_events: int,
    max_block_chars: int,
) -> None:
    """Generate a Markdown report for one app, including token usage totals."""
    init_app_logger(
        app_name=app_name,
        command_name="report",
        command_line=" ".join(sys.argv),
        options={
            "interactive_menu": interactive_menu,
            "include_sessions": include_sessions,
            "include_events": include_events,
            "include_prompts": include_prompts,
            "include_outputs": include_outputs,
            "include_audit_summary": include_audit_summary,
            "include_usage_files": include_usage_files,
            "max_events": max_events,
            "max_block_chars": max_block_chars,
        },
    )
    log_event("report.started", {"app_name": app_name, "interactive_menu": interactive_menu})

    app_dir = OUTPUTS_DIR / app_name
    if not app_dir.exists():
        console.print(f"[bold red]App output folder not found:[/bold red] {app_dir}")
        raise SystemExit(1)

    if interactive_menu:
        options = _interactive_report_options()
    else:
        options = _default_report_options()
        options.update(
            {
                "include_sessions": include_sessions,
                "include_events": include_events,
                "include_prompts": include_prompts,
                "include_outputs": include_outputs,
                "include_audit_summary": include_audit_summary,
                "include_usage_files": include_usage_files,
                "max_events": max(0, int(max_events)),
                "max_block_chars": max(200, int(max_block_chars)),
            }
        )
    log_event("report.options", options)

    usage_reports = _load_usage_reports(app_name)
    usage_agg = _aggregate_usage(usage_reports)
    log_data = _load_log_sections(app_name)
    audit_summary = _load_audit_summary(app_name)

    md = _render_markdown(
        app_name=app_name,
        options=options,
        usage_reports=usage_reports,
        usage_agg=usage_agg,
        log_data=log_data,
        audit_summary=audit_summary,
    )

    reports_dir = app_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%SZ")
    report_path = reports_dir / f"{ts}_app_report.md"
    latest_path = reports_dir / "latest_app_report.md"

    report_path.write_text(md, encoding="utf-8")
    latest_path.write_text(md, encoding="utf-8")

    log_event(
        "report.completed",
        {
            "report_path": str(report_path),
            "latest_path": str(latest_path),
            "total_tokens": float((usage_agg.get("totals") or {}).get("total_tokens") or 0.0),
        },
    )

    console.print(f"[bold green]✓ Report generated:[/bold green] {report_path}")
    console.print(f"[green]✓ Latest report:[/green] {latest_path}")
