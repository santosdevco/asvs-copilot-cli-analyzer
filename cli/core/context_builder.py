"""
context_builder.py
──────────────────
Assembles the context dict that is fed into prompt_renderer.render().

Two public functions:
  build_triage_context(app_name)                   → dict for components_creation.md
  build_audit_context(app_name, component_id, asvs_key) → dict for asvs_analysis.md

Static-context files follow the naming convention produced by run_mapper.py:
  {nn}_{report_name}.txt   e.g.  08_code_signals.txt
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any, Dict, List
import xml.etree.ElementTree as ET

from cli.config import (
    ASVS_ASSET_RELATION_FILE,
    ASVS_JSON_DIR,
    ASSET_CATEGORY_FILE,
    AUDIT_OUTPUT_FORMAT_FILE,
    AUDIT_OUTPUT_XML_FORMAT_FILE,
    COMPONENT_CTX_FORMAT_FILE,
    COMPONENT_CTX_XML_FORMAT_FILE,
    COMPONENT_INDEX_FORMAT_FILE,
    CONTEXT_CHOOSE_FILE,
    OUTPUTS_DIR,
)


# ── module-level static context cache (keyed by app_name, lives for process lifetime) ─
_static_xml_cache: Dict[str, str] = {}


# ── helpers ──────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _get_static_xml_path(app_name: str) -> Path:
    """Return the canonical XML static-context path for an app."""
    return OUTPUTS_DIR / app_name / "static_context.xml"


def _read_static_xml(app_name: str) -> str:
    """Return static_context.xml text, caching the result for the process lifetime."""
    if app_name not in _static_xml_cache:
        path = _get_static_xml_path(app_name)
        if not path.exists():
            raise FileNotFoundError(
                f"Static context XML not found at {path}. "
                "Run `extract --format xml` first."
            )
        _static_xml_cache[app_name] = path.read_text(encoding="utf-8")
    return _static_xml_cache[app_name]


def clear_static_cache() -> None:
    """Invalidate the static context cache (primarily for testing)."""
    _static_xml_cache.clear()


def _to_cdata(text: str) -> str:
    """Wrap arbitrary text as XML CDATA, preserving literal content."""
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def _parse_static_reports(xml_text: str, report_names: List[str]) -> str:
    """Extract selected reports from an already-loaded static_context.xml string."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid static context XML: {exc}") from exc

    selected_reports: list[str] = []
    needed = set(report_names)
    for report in root.findall("report"):
        report_type = (report.get("type") or "").strip().lower()
        if report_type not in needed:
            continue
        filename = escape((report.get("filename") or "").strip())
        rtype = escape(report_type)
        content = _to_cdata("".join(report.itertext()).strip())
        selected_reports.append(
            f"  <report type=\"{rtype}\" filename=\"{filename}\">{content}</report>"
        )

    return "\n".join(["<static_context>", *selected_reports, "</static_context>"])


def _load_static_reports(static_xml: Path, report_names: List[str]) -> str:
    """Extract selected reports from consolidated static_context.xml (reads from disk)."""
    return _parse_static_reports(static_xml.read_text(encoding="utf-8"), report_names)


def _format_asset_tags(asset_categories: list) -> str:
    """Convert asset_category.json list to a compact text reference."""
    lines = ["AVAILABLE ASSET TAGS (use these exact IDs in asset_tags fields):"]
    for cat in asset_categories:
        lines.append(f"  • {cat['asset_id']}: {cat['name']} — {cat['description'][:100]}...")
    return "\n".join(lines)


def _asvs_json_to_text(asvs_data: Dict[str, Any]) -> str:
    """Convert an ASVS chapter JSON into a dense plain-text format for LLM context."""
    chapter = asvs_data["chapter"]
    lines: List[str] = [
        f"CHAPTER {chapter['id']}: {chapter['title']}",
        f"OBJECTIVE: {chapter['control_objective']}",
        "",
    ]
    for section in chapter.get("sections", []):
        lines.append(f"SECTION {section['id']}: {section['title']}")
        if section.get("description"):
            lines.append(f"  {section['description']}")
        for req in section.get("requirements", []):
            lvl = req.get("level", "?")
            lines.append(f"  [{req['id']}] (L{lvl}) {req['description']}")
        lines.append("")
    return "\n".join(lines)


def _strip_auditor_diary(context_md: str) -> str:
    """No-op: context.xml no longer contains an auditor diary section.

    Kept for backward compatibility with code that imports this function.
    """
    return context_md


# ── public API ────────────────────────────────────────────────────────────────

def build_triage_context(app_name: str) -> Dict[str, str]:
    """Build the context dict for the Architect (triage) prompt."""
    # 1. Full static context in XML format (cached)
    full_static = _read_static_xml(app_name)

    # 2. Asset-tag reference (describes the allowed IDs)
    asset_categories = _load_json(ASSET_CATEGORY_FILE).get("asset_categories", [])
    asset_tags_txt = _format_asset_tags(asset_categories)

    # 3. Output format examples shown verbatim to the LLM
    component_json_format = COMPONENT_INDEX_FORMAT_FILE.read_text(encoding="utf-8")
    component_context_format = COMPONENT_CTX_XML_FORMAT_FILE.read_text(encoding="utf-8")

    return {
        "app_name": app_name,
        "asset_tags": asset_tags_txt,
        "component_json_format": component_json_format,
        "component_context_format": component_context_format,
        "full_static_context": full_static,
    }


def build_audit_context(
    app_name: str,
    component_id: str,
    asvs_key: str,           # e.g. "V6_Authentication"
    include_auditor_diary: bool = True,  # kept for backward compat; context.xml has no diary
) -> Dict[str, str]:
    """Build the context dict for the Audit-loop prompt."""
    component_dir = OUTPUTS_DIR / app_name / "components" / component_id

    # 1. ASVS chapter rules → plain text
    asvs_matrix = _load_json(ASVS_ASSET_RELATION_FILE)["asvs_routing_matrix"]
    chapter_meta = asvs_matrix[asvs_key]
    asvs_json_path = ASVS_JSON_DIR / chapter_meta["source_file"]
    asvs_rules_txt = _asvs_json_to_text(_load_json(asvs_json_path))

    # 2. Component context (context.xml, fallback to context.md for legacy outputs)
    context_xml_path = component_dir / "context.xml"
    context_md_path  = component_dir / "context.md"
    if context_xml_path.exists():
        context_content = context_xml_path.read_text(encoding="utf-8")
    elif context_md_path.exists():
        context_content = context_md_path.read_text(encoding="utf-8")
    else:
        context_content = ""

    # 3. Filtered static context based on context_choose.json (uses cache)
    context_choose = _load_json(CONTEXT_CHOOSE_FILE)
    v_num = asvs_key.split("_")[0]                           # "V6_Auth…" → "V6"
    tactical = context_choose["asvs_tactical_mapping"].get(v_num, {}).get("tactical_reports", [])
    core     = context_choose.get("core_reports", [])
    filtered_static = _parse_static_reports(_read_static_xml(app_name), core + tactical)

    # 4. Output format example (XML)
    audit_output_format = AUDIT_OUTPUT_XML_FORMAT_FILE.read_text(encoding="utf-8")

    return {
        "app_name": app_name,
        "component_key": component_id,
        "asvsid": v_num,
        "asvs_i_rules_txt": asvs_rules_txt,
        "context_md": context_content,      # key name kept; prompt reads it as <component_context>
        "filtered_static_context": filtered_static,
        "audit_output.xml": audit_output_format,
    }


def get_applicable_asvs_keys(asset_tags: List[str]) -> List[str]:
    """Return every ASVS chapter key whose target_assets overlap with *asset_tags*."""
    matrix = _load_json(ASVS_ASSET_RELATION_FILE)["asvs_routing_matrix"]
    tag_set = set(asset_tags)
    return [
        key
        for key, meta in matrix.items()
        if tag_set & set(meta.get("target_assets", []))
    ]
