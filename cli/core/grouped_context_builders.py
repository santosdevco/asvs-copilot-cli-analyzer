"""
grouped_context_builders.py
────────────────────────────
Assembles context dicts for grouped audit prompts (--group-by).

Two modes, two public functions:

  build_by_chapter_context(app_name, asvs_key, components, include_auditor_diary)
      → N components × 1 ASVS chapter  (used by asvs_chapter and asset_tags modes)

  build_by_component_context(app_name, component_id, asvs_keys, include_auditor_diary)
      → 1 component × N ASVS chapters  (used by component mode)

Dynamic multi-part blocks (component nodes, chapter nodes, output file lists) are
assembled as plain strings by Python so the renderer stays untouched ({{key}} only).
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Dict, List

from cli.config import (
    ASVS_ASSET_RELATION_FILE,
    ASVS_JSON_DIR,
    AUDIT_OUTPUT_GROUPED_FORMAT_FILE,
    CONTEXT_CHOOSE_FILE,
    OUTPUTS_DIR,
)
from cli.models import ComponentItem

# Re-use private helpers from sibling module — normal within-package usage
from cli.core.context_builder import (
    _asvs_json_to_text,
    _load_json,
    _parse_static_reports,
    _read_static_xml,
    _strip_auditor_diary,
    _to_cdata,
)


# ── internal helpers ──────────────────────────────────────────────────────────

def _component_dir(app_name: str, component_id: str) -> Path:
    return OUTPUTS_DIR / app_name / "components" / component_id


def _read_context_md(app_name: str, component_id: str, include_auditor_diary: bool) -> str:
    """Load a component's context.xml (falls back to context.md for legacy outputs)."""
    xml_path = _component_dir(app_name, component_id) / "context.xml"
    md_path  = _component_dir(app_name, component_id) / "context.md"
    if xml_path.exists():
        return xml_path.read_text(encoding="utf-8")
    text = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    return text if include_auditor_diary else _strip_auditor_diary(text)


def _tactical_report_names(asvs_key: str) -> list[str]:
    """Return core + tactical report names for a given ASVS key."""
    context_choose = _load_json(CONTEXT_CHOOSE_FILE)
    v_num = asvs_key.split("_")[0]           # "V6_Auth…" → "V6"
    core     = context_choose.get("core_reports", [])
    tactical = context_choose["asvs_tactical_mapping"].get(v_num, {}).get("tactical_reports", [])
    return core + tactical


def _chapter_meta(asvs_key: str) -> tuple[str, dict]:
    """Return (chapter_id, routing_matrix_entry) for an ASVS key."""
    matrix = _load_json(ASVS_ASSET_RELATION_FILE)["asvs_routing_matrix"]
    return asvs_key.split("_")[0], matrix[asvs_key]


def _output_file_path(app_name: str, component_id: str, chapter_id: str) -> str:
    return f"outputs/{app_name}/components/{component_id}/analysis/{chapter_id}.xml"


def _context_file_path(app_name: str, component_id: str) -> str:
    return f"outputs/{app_name}/components/{component_id}/context.xml"


def _wrap_component_context(context_text: str) -> str:
    """Embed context.xml as XML when available; otherwise wrap legacy text in CDATA."""
    stripped = context_text.strip()
    if stripped.startswith("<component_context>"):
        indented = "\n".join(f"    {line}" for line in stripped.splitlines())
        return f"{indented}\n"
    return f"    <component_context>{_to_cdata(context_text)}</component_context>\n"


# ── public API ────────────────────────────────────────────────────────────────

def build_by_chapter_context(
    app_name: str,
    asvs_key: str,
    components: List[ComponentItem],
    include_auditor_diary: bool = True,
) -> Dict[str, str]:
    """Context dict for the by-chapter grouped prompt (N components × 1 chapter).

    Template: asvs_analysis_by_chapter.md
    Keys returned:
      app_name, asvsid, component_count,
      asvs_i_rules_txt,
      outputs_xml       — pre-assembled <file> lines (N×2)
      components_xml    — pre-assembled <component> sub-nodes (one per component)
      audit_output_grouped.json
    """
    chapter_id, meta = _chapter_meta(asvs_key)
    asvs_rules_txt = _asvs_json_to_text(_load_json(ASVS_JSON_DIR / meta["source_file"]))
    report_names   = _tactical_report_names(asvs_key)

    # Warm the cache once before the loop
    xml_text = _read_static_xml(app_name)
    filtered_static = _parse_static_reports(xml_text, report_names)

    output_lines: list[str]    = []
    component_nodes: list[str] = []

    for comp in components:
        cid = comp.component_id
        context_md = _read_context_md(app_name, cid, include_auditor_diary)

        # Output file declarations (one per component, no context file — audit never modifies context)
        output_lines.append(
            f'    <file required="true">{_output_file_path(app_name, cid, chapter_id)}</file>'
        )

        # Component context node
        component_nodes.append(
            f'  <component id="{escape(cid)}" name="{escape(comp.component_name)}" '
            f'risk="{escape(comp.risk_level)}">\n'
            f'{_wrap_component_context(context_md)}'
            f'  </component>'
        )

    return {
        "app_name":                    app_name,
        "asvsid":                      chapter_id,
        "component_count":             str(len(components)),
        "asvs_i_rules_txt":            asvs_rules_txt,
        "filtered_static_context":     filtered_static,
        "outputs_xml":                 "\n".join(output_lines),
        "components_xml":              "\n".join(component_nodes),
        "audit_output_grouped.json":   AUDIT_OUTPUT_GROUPED_FORMAT_FILE.read_text(encoding="utf-8"),
    }


def build_by_component_context(
    app_name: str,
    component_id: str,
    asvs_keys: List[str],
    include_auditor_diary: bool = True,
) -> Dict[str, str]:
    """Context dict for the by-component grouped prompt (1 component × N chapters).

    Template: asvs_analysis_by_component.md
    Keys returned:
      app_name, component_key, chapter_count,
      context_md,
      filtered_static_context — union of all chapters' tactical reports
      outputs_xml             — pre-assembled <file> lines (context.md + N analysis files)
      chapters_xml            — pre-assembled <chapter> sub-nodes (one per chapter)
      audit_output_grouped.json
    """
    context_md = _read_context_md(app_name, component_id, include_auditor_diary)

    # Union all tactical report names across every chapter
    all_report_names: list[str] = []
    seen_reports: set[str] = set()
    for asvs_key in asvs_keys:
        for name in _tactical_report_names(asvs_key):
            if name not in seen_reports:
                all_report_names.append(name)
                seen_reports.add(name)

    xml_text = _read_static_xml(app_name)
    filtered_static = _parse_static_reports(xml_text, all_report_names)

    # Output files: one per chapter (no context file — audit never modifies context.xml)
    output_lines: list[str] = []
    chapter_nodes: list[str] = []

    for asvs_key in asvs_keys:
        chapter_id, meta = _chapter_meta(asvs_key)
        chapter_title = asvs_key.split("_", 1)[1].replace("_", " ") if "_" in asvs_key else chapter_id
        asvs_rules_txt = _asvs_json_to_text(_load_json(ASVS_JSON_DIR / meta["source_file"]))

        output_lines.append(
            f'    <file required="true">'
            f'{_output_file_path(app_name, component_id, chapter_id)}</file>'
        )
        chapter_nodes.append(
            f'  <chapter id="{escape(chapter_id)}" title="{escape(chapter_title)}">\n'
            f'    <rules>{_to_cdata(asvs_rules_txt)}</rules>\n'
            f'  </chapter>'
        )

    return {
        "app_name":                    app_name,
        "component_key":               component_id,
        "chapter_count":               str(len(asvs_keys)),
        "context_md":                  context_md,
        "filtered_static_context":     filtered_static,
        "outputs_xml":                 "\n".join(output_lines),
        "chapters_xml":                "\n".join(chapter_nodes),
        "audit_output_grouped.json":   AUDIT_OUTPUT_GROUPED_FORMAT_FILE.read_text(encoding="utf-8"),
    }
