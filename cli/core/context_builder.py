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
from pathlib import Path
from typing import Any, Dict, List

from cli.config import (
    ASVS_ASSET_RELATION_FILE,
    ASVS_JSON_DIR,
    ASSET_CATEGORY_FILE,
    AUDIT_OUTPUT_FORMAT_FILE,
    COMPONENT_CTX_FORMAT_FILE,
    COMPONENT_INDEX_FORMAT_FILE,
    CONTEXT_CHOOSE_FILE,
    OUTPUTS_DIR,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _find_static_file(static_dir: Path, report_name: str) -> Path | None:
    """Locate *{nn}_{report_name}.txt* inside *static_dir*, case-insensitive."""
    for candidate in static_dir.glob(f"*_{report_name}.txt"):
        return candidate
    return None


def _load_static_reports(static_dir: Path, report_names: List[str]) -> str:
    """Concatenate multiple static-context report files into a single string."""
    chunks: List[str] = []
    for name in report_names:
        path = _find_static_file(static_dir, name)
        if path and path.exists():
            chunks.append(f"=== [{name.upper()}] {path.name} ===\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(chunks)


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
    """Return context.md without the AUDITOR DIARY section and everything after it."""
    marker = "=== AUDITOR DIARY"
    idx = context_md.find(marker)
    if idx == -1:
        return context_md
    return context_md[:idx].rstrip()


# ── public API ────────────────────────────────────────────────────────────────

def build_triage_context(app_name: str) -> Dict[str, str]:
    """Build the context dict for the Architect (triage) prompt."""
    static_dir = OUTPUTS_DIR / app_name / "static_context"
    if not static_dir.exists():
        raise FileNotFoundError(
            f"Static context not found at {static_dir}. "
            "Run `extract` first."
        )

    # 1. Full static context – concatenate every .txt file
    full_static = "\n\n".join(
        f"=== {f.name} ===\n{f.read_text(encoding='utf-8')}"
        for f in sorted(static_dir.glob("*.txt"))
    )

    # 2. Asset-tag reference (describes the allowed IDs)
    asset_categories = _load_json(ASSET_CATEGORY_FILE).get("asset_categories", [])
    asset_tags_txt = _format_asset_tags(asset_categories)

    # 3. Output format examples shown verbatim to the LLM
    component_json_format = COMPONENT_INDEX_FORMAT_FILE.read_text(encoding="utf-8")
    component_context_format = COMPONENT_CTX_FORMAT_FILE.read_text(encoding="utf-8")

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
    include_auditor_diary: bool = True,
) -> Dict[str, str]:
    """Build the context dict for the Audit-loop prompt."""
    static_dir = OUTPUTS_DIR / app_name / "static_context"
    component_dir = OUTPUTS_DIR / app_name / "components" / component_id

    # 1. ASVS chapter rules → plain text
    asvs_matrix = _load_json(ASVS_ASSET_RELATION_FILE)["asvs_routing_matrix"]
    chapter_meta = asvs_matrix[asvs_key]
    asvs_json_path = ASVS_JSON_DIR / chapter_meta["source_file"]
    asvs_rules_txt = _asvs_json_to_text(_load_json(asvs_json_path))

    # 2. Auditor diary (current component context)
    context_md_path = component_dir / "context.md"
    context_md = context_md_path.read_text(encoding="utf-8") if context_md_path.exists() else ""
    if not include_auditor_diary:
        context_md = _strip_auditor_diary(context_md)

    # 3. Filtered static context based on context_choose.json
    context_choose = _load_json(CONTEXT_CHOOSE_FILE)
    v_num = asvs_key.split("_")[0]                           # "V6_Auth…" → "V6"
    tactical = context_choose["asvs_tactical_mapping"].get(v_num, {}).get("tactical_reports", [])
    core     = context_choose.get("core_reports", [])
    filtered_static = _load_static_reports(static_dir, core + tactical)

    # 4. Output format example
    audit_output_format = AUDIT_OUTPUT_FORMAT_FILE.read_text(encoding="utf-8")

    return {
        "app_name": app_name,
        "component_key": component_id,
        "asvsid": v_num,                     # Add the ASVS chapter ID (e.g., "V1", "V6")
        "asvs_i_rules_txt": asvs_rules_txt,
        "context_md": context_md,
        "filtered_static_context": filtered_static,
        "audit_output.json": audit_output_format,
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
