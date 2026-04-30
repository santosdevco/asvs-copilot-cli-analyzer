"""
output_writer.py
────────────────
Writes and updates the pipeline artefacts:

  write_component_index(app_name, index)
  write_component_context(app_name, component_id, content)
  write_audit_result(app_name, component_id, asvs_key, audit_output)
  append_context_notes(app_name, component_id, notes)
  load_component_index(app_name)  → ComponentIndex
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from cli.config import OUTPUTS_DIR
from cli.models import AuditOutput, ComponentIndex


# ── Path helpers ──────────────────────────────────────────────────────────────

def _components_dir(app_name: str) -> Path:
    return OUTPUTS_DIR / app_name / "components"


def _component_dir(app_name: str, component_id: str) -> Path:
    return _components_dir(app_name) / component_id


def _analysis_dir(app_name: str, component_id: str) -> Path:
    return _component_dir(app_name, component_id) / "analysis"


def _current_llm_model() -> str | None:
    """Best-effort resolve of the currently configured LLM model."""
    try:
        from cli.core.llm_client import get_provider_and_model

        _, model = get_provider_and_model()
        return model
    except Exception:
        return None


def _usage_dir(app_name: str) -> Path:
    return OUTPUTS_DIR / app_name / "usage"


def _normalize_duration_to_seconds(raw_duration: float | int | None) -> float:
    """Normalize SDK duration values to seconds.

    Copilot usage events may return duration in milliseconds. When the value is
    implausibly large for seconds, treat it as milliseconds.
    """
    value = float(raw_duration or 0.0)
    if value > 10_000:
        return value / 1000.0
    return value


# ── Writers ───────────────────────────────────────────────────────────────────

def write_component_index(app_name: str, index: ComponentIndex) -> Path:
    """Persist index.json for *app_name*."""
    dest = _components_dir(app_name) / "index.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        index.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )
    return dest


def write_component_context(
    app_name: str,
    component_id: str,
    content: str,
) -> Path:
    """Write (overwrite) context.xml for a component."""
    dest = _component_dir(app_name, component_id) / "context.xml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    return dest


def append_context_notes(
    app_name: str,
    component_id: str,
    notes: List[str],
    lock: threading.Lock | None = None,
) -> None:
    """No-op: auditor diary notes are now embedded in the chapter XML file.

    Kept for backward compatibility so existing call-sites do not break.
    """


def _audit_output_to_xml(result: AuditOutput, component_id: str, chapter_id: str) -> str:
    """Serialise an AuditOutput pydantic model to the audit_result XML format."""
    from datetime import date
    from xml.sax.saxutils import escape as _esc

    lines: list[str] = ["<audit_result>"]
    lines.append(f"  <component_id>{_esc(component_id)}</component_id>")
    lines.append(f"  <asvs_chapter>{_esc(chapter_id)}</asvs_chapter>")
    lines.append(f"  <audit_date>{date.today().isoformat()}</audit_date>")

    passed = sum(1 for r in result.audit_results if r.status == "PASS")
    failed = sum(1 for r in result.audit_results if r.status == "FAIL")
    na     = sum(1 for r in result.audit_results if r.status == "NOT_APPLICABLE")
    lines.append(f'  <summary passed="{passed}" failed="{failed}" not_applicable="{na}" />')

    lines.append("  <requirements>")
    for req in result.audit_results:
        sev = f' severity="{_esc(req.severity)}"' if req.severity else ""
        lines.append(f'    <requirement id="{_esc(req.requirement_id)}" status="{_esc(req.status)}"{sev}>')
        if req.vulnerability_title:
            lines.append(f"      <vulnerability_title>{_esc(req.vulnerability_title)}</vulnerability_title>")
        if req.description:
            lines.append(f"      <description>{_esc(req.description)}</description>")
        if req.affected_file:
            lines.append(f"      <affected_file>{_esc(req.affected_file)}</affected_file>")
        if req.affected_function:
            lines.append(f"      <affected_function>{_esc(req.affected_function)}</affected_function>")
        if req.line_range:
            lines.append(f'      <line_range start="{req.line_range[0]}" end="{req.line_range[1]}" />')
        if req.remediation_hint:
            lines.append(f"      <remediation_hint>{_esc(req.remediation_hint)}</remediation_hint>")
        lines.append("    </requirement>")
    lines.append("  </requirements>")

    if result.context_update_notes:
        lines.append("  <auditor_diary>")
        for note in result.context_update_notes:
            lines.append(f"    <finding>{_esc(note)}</finding>")
        lines.append("  </auditor_diary>")

    lines.append("</audit_result>")
    return "\n".join(lines)


def write_audit_result(
    app_name: str,
    component_id: str,
    asvs_key: str,           # e.g. "V6_Authentication"
    result: AuditOutput,
    context_lock: threading.Lock | None = None,
) -> Path:
    """Persist a chapter audit XML file.

    Technical discoveries (context_update_notes) are embedded in the XML
    <auditor_diary> block.  context.xml is never modified here.
    The ``context_lock`` parameter is kept for backward compatibility.
    """
    analysis_dir = _analysis_dir(app_name, component_id)
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # e.g. V6_Authentication → V6
    chapter_id = asvs_key.split("_")[0]
    dest_xml = analysis_dir / f"{chapter_id}.xml"
    dest_xml.write_text(
        _audit_output_to_xml(result, component_id, chapter_id),
        encoding="utf-8",
    )

    # Keep a JSON sibling alongside XML so downstream tooling can aggregate audits.
    json_payload = result.model_dump(mode="json", exclude_none=True)
    llm_model = _current_llm_model()
    if llm_model:
        json_payload["llm_model"] = llm_model

    dest_json = analysis_dir / f"{chapter_id}.json"
    dest_json.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return dest_xml


def write_usage_report(
    app_name: str,
    command_name: str,
    calls: list[dict],
    provider: str | None = None,
    model: str | None = None,
    metadata: dict | None = None,
) -> Path:
    """Persist real token usage report for a command execution."""
    usage_dir = _usage_dir(app_name)
    usage_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")

    totals = {
        "input_tokens": 0.0,
        "output_tokens": 0.0,
        "cache_read_tokens": 0.0,
        "cache_write_tokens": 0.0,
        "reasoning_tokens": 0.0,
        "cost": 0.0,
        "duration_seconds": 0.0,
        "assistant_usage_events": 0,
    }

    token_detail_totals: dict[str, float] = {}

    for call in calls:
        usage = call.get("usage") or {}
        totals["input_tokens"] += float(usage.get("input_tokens") or 0.0)
        totals["output_tokens"] += float(usage.get("output_tokens") or 0.0)
        totals["cache_read_tokens"] += float(usage.get("cache_read_tokens") or 0.0)
        totals["cache_write_tokens"] += float(usage.get("cache_write_tokens") or 0.0)
        totals["reasoning_tokens"] += float(usage.get("reasoning_tokens") or 0.0)
        totals["cost"] += float(usage.get("cost") or 0.0)
        totals["duration_seconds"] += _normalize_duration_to_seconds(usage.get("duration"))
        totals["assistant_usage_events"] += int(usage.get("usage_event_count") or 0)

        for detail in usage.get("token_details", []):
            token_type = str(detail.get("token_type") or "unknown")
            token_count = float(detail.get("token_count") or 0.0)
            token_detail_totals[token_type] = token_detail_totals.get(token_type, 0.0) + token_count

    totals["total_tokens"] = totals["input_tokens"] + totals["output_tokens"]

    report = {
        "generated_at": now.isoformat(),
        "app_name": app_name,
        "command": command_name,
        "provider": provider,
        "model": model,
        "calls_count": len(calls),
        "totals": totals,
        "token_detail_totals": token_detail_totals,
        "calls": calls,
        "metadata": metadata or {},
    }

    report_path = usage_dir / f"{timestamp}_{command_name}_usage.json"
    latest_path = usage_dir / f"latest_{command_name}_usage.json"

    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report_path


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_component_index(app_name: str) -> ComponentIndex:
    path = _components_dir(app_name) / "index.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Component index not found at {path}. Run `triage` first."
        )
    return ComponentIndex.model_validate_json(path.read_text(encoding="utf-8"))
