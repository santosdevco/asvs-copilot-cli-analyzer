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
    _read_component_context,
    _asvs_json_to_text,
    _format_files_to_audit,
    _get_component_scope_paths,
    _load_json,
    _parse_static_reports,
    _read_static_xml,
    _to_cdata,
)


# ── internal helpers ──────────────────────────────────────────────────────────

def _component_dir(app_name: str, component_id: str) -> Path:
    return OUTPUTS_DIR / app_name / "components" / component_id


def _read_context_md(app_name: str, component_id: str, include_auditor_diary: bool) -> str:
    """Load component context honoring CONTEXT_FORMAT through shared reader."""
    return _read_component_context(app_name, component_id, include_auditor_diary)


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
    return f"outputs/{app_name}/components/{component_id}/analysis/{chapter_id}.json" # TODO se puede hacer le formato parametrizable, pero json es el mas opimo en este momento


def _context_file_path(app_name: str, component_id: str) -> str:
    return f"outputs/{app_name}/components/{component_id}/context.xml"


def _wrap_component_context(context_text: str) -> str:
    """Embed context.xml as XML when available; otherwise wrap legacy text in CDATA."""
    stripped = context_text.strip()
    if stripped.startswith("<component_context>"):
        indented = "\n".join(f"    {line}" for line in stripped.splitlines())
        return f"{indented}\n"
    return f"    <component_context>{_to_cdata(context_text)}</component_context>\n"


def _format_grouped_files_to_audit(component_paths_by_id: dict[str, list[str]]) -> str:
    """Render files_to_audit grouped by component so the prompt preserves ownership."""
    blocks: list[str] = []
    for component_id, paths in component_paths_by_id.items():
        rendered_paths = _format_files_to_audit(paths)
        blocks.append(
            f'  <component_paths component_id="{escape(component_id)}">\n'
            f'{_to_cdata(rendered_paths)}\n'
            f'  </component_paths>'
        )
    return "\n".join(blocks)


# ── public API ────────────────────────────────────────────────────────────────

def build_by_chapter_context(
    app_name: str,
    asvs_key: str,
    components: List[ComponentItem],
    include_auditor_diary: bool = True,
    prompt_sections: str = "component_context,filtered_static_context,file_contents,files_to_audit",
) -> Dict[str, str]:
    """Context dict for the by-chapter grouped prompt (N components × 1 chapter).

    Template: asvs_analysis_by_chapter.md
    Keys returned:
      app_name, asvsid, component_count,
      asvs_i_rules_txt,
      outputs_xml       — pre-assembled <file> lines (N×2)
      components_xml    — pre-assembled <component> sub-nodes (one per component)
      audit_output_grouped.json
      file_contents     — optional XML with file contents (if "file_contents" in prompt_sections)
    """
    from cli.core.context_builder import _build_file_contents_xml

    chapter_id, meta = _chapter_meta(asvs_key)
    asvs_rules_txt = _asvs_json_to_text(_load_json(ASVS_JSON_DIR / meta["source_file"]))
    report_names   = _tactical_report_names(asvs_key)

    # Warm the cache once before the loop
    xml_text = _read_static_xml(app_name)

    # Slice static reports using the union of all component paths in this grouped request.
    all_component_paths: list[str] = []
    all_core_paths: list[str] = []
    component_paths_by_id: dict[str, list[str]] = {}
    for comp in components:
        component_paths, core_paths = _get_component_scope_paths(app_name, comp.component_id)
        component_paths_by_id[comp.component_id] = component_paths + core_paths
        all_component_paths.extend(component_paths)
        all_core_paths.extend(core_paths)

    filtered_static = _parse_static_reports(
        xml_text,
        report_names,
        component_paths=all_component_paths,
        core_paths=all_core_paths,
    )
    files_to_audit = _format_grouped_files_to_audit(component_paths_by_id)

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

    # Build file contents XML if requested
    file_contents_xml = ""
    if "file_contents" in prompt_sections:
        # Combine all component paths for file content inclusion
        all_paths = list(set(all_component_paths))
        if all_paths:
            file_contents_xml = _build_file_contents_xml(app_name, all_paths)

    return {
        "app_name":                    app_name,
        "asvsid":                      chapter_id,
        "component_count":             str(len(components)),
        "asvs_i_rules_txt":            asvs_rules_txt,
        "files_to_audit":              files_to_audit,
        "filtered_static_context":     filtered_static,
        "outputs_xml":                 "\n".join(output_lines),
        "components_xml":              "\n".join(component_nodes),
        "audit_output_grouped.json":   AUDIT_OUTPUT_GROUPED_FORMAT_FILE.read_text(encoding="utf-8"),
        "file_contents":               file_contents_xml,
    }


def build_by_component_context(
    app_name: str,
    component_id: str,
    asvs_keys: List[str],
    include_auditor_diary: bool = True,
    prompt_sections: str = "component_context,filtered_static_context,file_contents,files_to_audit",
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
      file_contents           — optional XML with file contents (if add_file_content=True)
    """
    from cli.core.context_builder import _build_file_contents_xml

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
    component_paths, core_paths = _get_component_scope_paths(app_name, component_id)
    filtered_static = _parse_static_reports(
        xml_text,
        all_report_names,
        component_paths=component_paths,
        core_paths=core_paths,
    )
    files_to_audit = _format_grouped_files_to_audit(
        {component_id: component_paths + core_paths}
    )

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

    # Build file contents XML if requested
    file_contents_xml = ""
    if "file_contents" in prompt_sections and component_paths:
        file_contents_xml = _build_file_contents_xml(app_name, component_paths)

    return {
        "app_name":                    app_name,
        "component_key":               component_id,
        "chapter_count":               str(len(asvs_keys)),
        "context_md":                  context_md,
        "files_to_audit":              files_to_audit,
        "filtered_static_context":     filtered_static,
        "outputs_xml":                 "\n".join(output_lines),
        "chapters_xml":                "\n".join(chapter_nodes),
        "audit_output_grouped.json":   AUDIT_OUTPUT_GROUPED_FORMAT_FILE.read_text(encoding="utf-8"),
        "file_contents":               file_contents_xml,
    }
