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
import warnings
from html import escape
from pathlib import Path
from typing import Any, Dict, List
import xml.etree.ElementTree as ET

from cli.config import (
    ASVS_ASSET_RELATION_FILE,
    ASVS_JSON_DIR,
    ASSET_CATEGORY_FILE,
    AUDIT_OUTPUT_FORMAT_FILE,
    AUDIT_OUTPUT_JSON_FORMAT_FILE,
    AUDIT_OUTPUT_XML_FORMAT_FILE,
    COMPONENT_CTX_FORMAT_FILE,
    COMPONENT_CTX_XML_FORMAT_FILE,
    COMPONENT_CTX_YML_FORMAT_FILE,
    COMPONENT_INDEX_FORMAT_FILE,
    CONTEXT_FORMAT,
    CONTEXT_CHOOSE_FILE,
    OUTPUTS_DIR,
    ANALYSIS_OUTPUT_FORMAT
)
from cli.core.app_logger import log_event


# ── module-level static context cache (keyed by app_name, lives for process lifetime) ─
_static_xml_cache: Dict[str, str] = {}


# ── helpers ──────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _get_static_xml_path(app_name: str) -> Path:
    """Return the canonical XML static-context path for an app."""
    return OUTPUTS_DIR / app_name / "static_context.xml"


def _context_format_preference() -> str:
    """Return context format preference from config (xml|md|yml|auto)."""
    value = CONTEXT_FORMAT
    if value in {"yaml", "yml"}:
        return "yaml"
    if value in {"xml", "md", "auto"}:
        return value
    return "auto"


def _warn_missing_context(
    app_name: str,
    component_id: str,
    expected_format: str,
    expected_path: Path,
) -> None:
    """Emit a warning when the requested context format is missing for a component."""
    message = (
        f"CONTEXT_FORMAT={expected_format} requested but context file was not found: "
        f"{expected_path} (app={app_name}, component={component_id}). "
        "Proceeding with empty component context."
    )
    warnings.warn(message, stacklevel=2)
    log_event(
        "context.missing_requested_format",
        {
            "app_name": app_name,
            "component_id": component_id,
            "context_format": expected_format,
            "expected_path": str(expected_path),
        },
    )


def _read_component_context(
    app_name: str,
    component_id: str,
    include_auditor_diary: bool = True,
) -> str:
    """
    Read component context honoring CONTEXT_FORMAT env.

    CONTEXT_FORMAT behavior:
      - xml: only context.xml; missing file returns empty string and emits warning.
      - md: only context.md; missing file returns empty string and emits warning.
      - yml: only context.yml; missing file returns empty string and emits warning.
      - auto/default: xml first, then md legacy fallback.
    """
    component_dir = OUTPUTS_DIR / app_name / "components" / component_id
    xml_path = component_dir / "context.xml"
    md_path = component_dir / "context.md"
    yml_path = component_dir / "context.yml"
    
    preferred = _context_format_preference()
    # print(
    #     f"context.read_request app={app_name} component={component_id} prefered={preferred}",
    # )
    if preferred == "xml":
        if xml_path.exists():
            return xml_path.read_text(encoding="utf-8")
        _warn_missing_context(app_name, component_id, "xml", xml_path)
        return ""

    if preferred == "md":
        
        if md_path.exists():
            text = md_path.read_text(encoding="utf-8")
            return text if include_auditor_diary else _strip_auditor_diary(text)
        _warn_missing_context(app_name, component_id, "md", md_path)
        return ""

    if preferred == "yaml":
        # log_event(f"context.yml_requested {yml_path}")
        if yml_path.exists():
            return yml_path.read_text(encoding="utf-8")
        _warn_missing_context(app_name, component_id, "yml", yml_path)
        return ""

    # auto/default
    if xml_path.exists():
        return xml_path.read_text(encoding="utf-8")
    if md_path.exists():
        text = md_path.read_text(encoding="utf-8")
        return text if include_auditor_diary else _strip_auditor_diary(text)
    return ""


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


def _add_line_numbers(content: str) -> str:
    """
    Add line numbers to file content with proper alignment.

    Format: "[padded_line_number] | [original_line]"
    Padding is based on total line count for vertical alignment.

    Preserves original indentation and handles empty lines.
    Memory-efficient: processes content line-by-line.
    """
    if not content:
        return content

    lines = content.splitlines(keepends=True)
    if not lines:
        return content

    # Calculate padding width based on total number of lines
    total_lines = len(lines)
    line_num_width = len(str(total_lines))

    # Build result with numbered lines
    numbered_lines: list[str] = []
    for i, line in enumerate(lines, 1):
        # Right-align the line number with padding
        padded_num = str(i).rjust(line_num_width)

        # Handle lines with/without newline
        if line.endswith(('\n', '\r\n', '\r')):
            # Remove newline to process, we'll add it back
            line_content = line.rstrip('\n\r')
            numbered_lines.append(f"{padded_num} | {line_content}\n")
        else:
            # Last line without newline
            numbered_lines.append(f"{padded_num} | {line}")

    return "".join(numbered_lines)


def _clean_target_paths(paths: List[str]) -> List[str]:
    """Normalize and deduplicate target paths used for line-based matching."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not isinstance(path, str):
            continue
        value = path.replace("*", "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


_BANNED_HEADERS = frozenset([
    "[BLAST RADIUS",
    "[LARGEST FILES]",
    "[MOST COMPLEX FILES]",
    "[CLIENT-SIDE ROUTES]",
])

from typing import List, Optional

def _slice_report_content(
    raw_text: str, 
    component_paths: Optional[List[str]] = None, 
    core_paths: Optional[List[str]] = None
) -> str:
    """Filter report content line-by-line using FILE-tagged lines and path matching.

    Blocks introduced by a BANNED_HEADERS marker are skipped entirely to reduce
    token usage. A new non-banned section header (starts with '[', ends with ']')
    resets skip_mode so subsequent lines are processed normally.
    
    If no paths are provided (Triage mode), it applies skip_mode but keeps all files.
    """
    # Manejar listas vacías o None de forma segura
    comp_paths = component_paths or []
    cor_paths = core_paths or []
    
    all_targets = _clean_target_paths(cor_paths) + _clean_target_paths(comp_paths)

    filtered_lines: list[str] = []
    skip_mode = False
    
    for line in raw_text.splitlines():
        # Check for a banned section header → enter skip mode
        if any(banned in line for banned in _BANNED_HEADERS):
            skip_mode = True
            continue

        # Check for a new (non-banned) section header → exit skip mode
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            skip_mode = False

        if skip_mode:
            continue

        # Original path-matching logic + Soporte para Triage (all_targets vacío)
        if "FILE:" in line:
            # Si NO hay targets (Triage), deja pasar todos los archivos.
            # Si SÍ hay targets (Audit), filtra solo los que hagan match.
            if not all_targets or any(target in line for target in all_targets):
                filtered_lines.append(line)
        else:
            filtered_lines.append(line)
            
    return "\n".join(filtered_lines)

def _get_component_scope_paths(app_name: str, component_id: str) -> tuple[List[str], List[str]]:
    """Read component and core paths from outputs/<app>/components/index.json."""
    index_path = OUTPUTS_DIR / app_name / "components" / "index.json"
    if not index_path.exists():
        return [], []

    try:
        index_data = _load_json(index_path)
    except Exception:
        return [], []

    core_paths = index_data.get("core_paths", [])
    project_triage = index_data.get("project_triage", [])

    component_paths: list[str] = []
    for item in project_triage:
        if item.get("component_id") == component_id:
            component_paths = item.get("files_to_audit", [])
            break

    return component_paths, core_paths


def _get_component_index_entry(app_name: str, component_id: str) -> dict[str, Any]:
    """Return the raw component entry from outputs/<app>/components/index.json."""
    index_path = OUTPUTS_DIR / app_name / "components" / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(
            f"Component index not found at {index_path}. Run `triage` first."
        )

    index_data = _load_json(index_path)
    for item in index_data.get("project_triage", []):
        if item.get("component_id") == component_id:
            return item

    raise KeyError(f"Component '{component_id}' not found in {index_path}")


def _report_names_for_asset_tags(asset_tags: List[str]) -> List[str]:
    """Resolve core + tactical report names for a set of asset tags."""
    context_choose = _load_json(CONTEXT_CHOOSE_FILE)
    report_names: list[str] = []
    seen: set[str] = set()

    for name in context_choose.get("core_reports", []):
        if name not in seen:
            report_names.append(name)
            seen.add(name)

    tactical_mapping = context_choose.get("asvs_tactical_mapping", {})
    for asvs_key in get_applicable_asvs_keys(asset_tags):
        chapter_id = asvs_key.split("_")[0]
        for name in tactical_mapping.get(chapter_id, {}).get("tactical_reports", []):
            if name not in seen:
                report_names.append(name)
                seen.add(name)

    return report_names


def _format_files_to_audit(paths: List[str]) -> str:
    """Render files_to_audit as newline-delimited paths for prompts."""
    cleaned = _clean_target_paths(paths)
    if not cleaned:
        return ""
    return "\n".join(cleaned)


def _extract_source_dir_from_static(app_name: str) -> str:
    """Parse the Project path from the identity report in static_context.xml.

    Looks for a line like:  Project : /some/absolute/path
    Returns the path string, or empty string if not found.
    """
    try:
        xml_text = _read_static_xml(app_name)
        root = ET.fromstring(xml_text)
        for report in root.findall("report"):
            if (report.get("type") or "").strip().lower() == "identity":
                text = "".join(report.itertext())
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.lower().startswith("project :"):
                        return stripped.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


def _get_source_dir_path(app_name: str) -> Path:
    """Get the source directory path from index.json."""
    index_path = OUTPUTS_DIR / app_name / "components" / "index.json"
    if not index_path.exists():
        # Fallback to default repo path
        return OUTPUTS_DIR / app_name / "repo"

    try:
        index_data = _load_json(index_path)
        source_dir = index_data.get("source_dir_path", "")
        if source_dir:
            # source_dir_path is relative to BASE_DIR (repo root)
            from cli.config import BASE_DIR
            return BASE_DIR / source_dir
    except Exception:
        pass

    # Fallback to default repo path
    return OUTPUTS_DIR / app_name / "repo"


def _read_file_content_safe(file_path: str, app_name: str) -> str:
    """Read file content safely, handling errors and binary files.

    Automatically adds line numbers with proper alignment for LLM context.
    Format: "[padded_line_number] | [original_line_content]"
    """
    try:
        source_dir = _get_source_dir_path(app_name)
        full_path = source_dir / file_path.lstrip("./")

        log_event(
            "context.read_file_content",
            {
                "app_name": app_name,
                "file_path": file_path,
                "source_dir": str(source_dir),
                "full_path": str(full_path),
                "exists": full_path.exists(),
            },
        )

        if not full_path.exists():
            return f"<!-- File not found: {file_path} (full path: {full_path}) -->"

        # Skip large files (> 500KB)
        if full_path.stat().st_size > 500_000:
            return f"<!-- File too large (>{full_path.stat().st_size / 1024:.0f}KB): {file_path} -->"

        content = full_path.read_text(encoding="utf-8")

        # Add line numbers for better LLM context
        numbered_content = _add_line_numbers(content)

        log_event(
            "context.file_content_read",
            {
                "file_path": file_path,
                "size_bytes": full_path.stat().st_size,
                "line_count": len(content.splitlines()),
            },
        )
        return numbered_content
    except UnicodeDecodeError:
        return f"<!-- Binary file skipped: {file_path} -->"
    except Exception as e:
        log_event(
            "context.read_file_error",
            {"file_path": file_path, "error": str(e)},
        )
        return f"<!-- Error reading file: {file_path} - {str(e)} -->"


def _build_file_contents_xml(app_name: str, file_paths: List[str]) -> str:
    """Build XML section with file contents for the specified paths."""
    if not file_paths:
        return ""

    cleaned_paths = _clean_target_paths(file_paths)
    if not cleaned_paths:
        return ""

    file_entries: list[str] = []
    for file_path in cleaned_paths:
        content = _read_file_content_safe(file_path, app_name)
        escaped_path = escape(file_path)
        file_entries.append(
            f'  <file path="{escaped_path}">{_to_cdata(content)}</file>'
        )

    return "\n".join([
        # "<file_contents>",
        *file_entries,
        # "</file_contents>"
    ])


def _parse_static_reports(
    xml_text: str,
    report_names: List[str],
    component_paths: List[str] | None = None,
    core_paths: List[str] | None = None,
) -> str:
    """Extract selected reports and optionally slice FILE-tagged lines by component/core paths."""
    component_paths = component_paths or []
    core_paths = core_paths or []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid static context XML: {exc}") from exc

    selected_reports: list[str] = []
    needed = set(report_names)
    reports_to_slice = {"code_signals", "frontend", "imports"}

    for report in root.findall("report"):
        report_type = (report.get("type") or "").strip().lower()
        if report_type not in needed:
            continue

        filename = escape((report.get("filename") or "").strip())
        rtype = escape(report_type)
        raw_content = "".join(report.itertext()).strip()

        if report_type in reports_to_slice and (component_paths or core_paths):
            processed_content = _slice_report_content(raw_content, component_paths, core_paths)
        else:
            processed_content = raw_content

        content = _to_cdata(processed_content)
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
        # f"OBJECTIVE: {chapter['control_objective']}",
        "",
    ]
    for section in chapter.get("sections", []):
        lines.append(f"SECTION {section['id']}: {section['title']}")
        # if section.get("description"):
        #     lines.append(f"  {section['description']}")
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
    # Respect CONTEXT_FORMAT env var
    preferred = _context_format_preference()

    # Use _parse_static_reports so each report's content is CDATA-wrapped
    # properly — avoids injecting raw XML into the prompt which causes
    # truncated/corrupt documents when reports contain < > & or ]]> sequences.
    context_choose = _load_json(CONTEXT_CHOOSE_FILE)
    all_report_names = list(context_choose.get("core_reports", []))
    seen: set[str] = set(all_report_names)
    for v in context_choose.get("asvs_tactical_mapping", {}).values():
        for name in v.get("tactical_reports", []):
            if name not in seen:
                all_report_names.append(name)
                seen.add(name)

    full_static = _parse_static_reports(_read_static_xml(app_name), all_report_names)

    # 1. Full static context in preferred format
    if preferred in ("yaml", "yml"):
        component_context_format = COMPONENT_CTX_YML_FORMAT_FILE.read_text(encoding="utf-8")    
    else:
        component_context_format = COMPONENT_CTX_XML_FORMAT_FILE.read_text(encoding="utf-8")

    # 2. Asset-tag reference (describes the allowed IDs)
    asset_categories = _load_json(ASSET_CATEGORY_FILE).get("asset_categories", [])
    asset_tags_txt = _format_asset_tags(asset_categories)

    # 3. Output format examples shown verbatim to the LLM
    component_json_format = COMPONENT_INDEX_FORMAT_FILE.read_text(encoding="utf-8")
    source_dir_path = _extract_source_dir_from_static(app_name)
    return {
        "app_name": app_name,
        "asset_tags": asset_tags_txt,
        "component_json_format": component_json_format,
        "component_context_format": component_context_format,
        "full_static_context": full_static,
        "source_dir_path": source_dir_path,
    }


def build_audit_context(
    app_name: str,
    component_id: str,
    asvs_key: str,           # e.g. "V6_Authentication"
    include_auditor_diary: bool = True,  # kept for backward compat; context.xml has no diary
    prompt_sections: str = "component_context,filtered_static_context,file_contents,files_to_audit",
) -> Dict[str, str]:
    """Build the context dict for the Audit-loop prompt.

    prompt_sections: comma-separated list of sections to include
      - component_context: component analysis context
      - filtered_static_context: static context reports (core + tactical)
      - file_contents: actual file code (with line numbers)
      - files_to_audit: list of files to audit
    """
    # 1. ASVS chapter rules → plain text
    asvs_matrix = _load_json(ASVS_ASSET_RELATION_FILE)["asvs_routing_matrix"]
    chapter_meta = asvs_matrix[asvs_key]
    asvs_json_path = ASVS_JSON_DIR / chapter_meta["source_file"]
    asvs_rules_txt = _asvs_json_to_text(_load_json(asvs_json_path))

    # 2. Component context (honors CONTEXT_FORMAT env)
    context_content = _read_component_context(app_name, component_id, include_auditor_diary)

    # 3. Filtered static context based on context_choose.json (uses cache)
    context_choose = _load_json(CONTEXT_CHOOSE_FILE)
    v_num = asvs_key.split("_")[0]                           # "V6_Auth…" → "V6"
    tactical = context_choose["asvs_tactical_mapping"].get(v_num, {}).get("tactical_reports", [])
    core     = context_choose.get("core_reports", [])
    component_paths, core_paths = _get_component_scope_paths(app_name, component_id)
    filtered_static = _parse_static_reports(
        _read_static_xml(app_name),
        core + tactical,
        component_paths=component_paths,
        core_paths=core_paths,
    )
    if ANALYSIS_OUTPUT_FORMAT == 'xml':
        # 4. Output format example (XML)
        audit_output_format = AUDIT_OUTPUT_XML_FORMAT_FILE.read_text(encoding="utf-8")
    else:
        audit_output_format = AUDIT_OUTPUT_JSON_FORMAT_FILE.read_text(encoding="utf-8")
        

    # Parse prompt sections to include
    sections_set = set(s.strip() for s in prompt_sections.split(",") if s.strip())

    # 5. Build context dict with conditional sections
    context = {
        "app_name": app_name,
        "component_key": component_id,
        "asvsid": v_num,
        "asvs_i_rules_txt": asvs_rules_txt,
        "audit_output.xml": audit_output_format,
    }

    # Add conditional sections
    if "component_context" in sections_set:
        context["context_md"] = context_content
    else:
        context["context_md"] = ""

    if "filtered_static_context" in sections_set:
        context["filtered_static_context"] = filtered_static
    else:
        context["filtered_static_context"] = ""

    if "files_to_audit" in sections_set:
        context["files_to_audit"] = _format_files_to_audit(component_paths)
    else:
        context["files_to_audit"] = ""

    # 6. Optionally add file contents (with line numbers)
    if "file_contents" in sections_set:
        # Combine core_paths and component_paths, removing duplicates
        combined_paths = list(dict.fromkeys(core_paths + component_paths))
        if combined_paths:
            context["file_contents"] = _build_file_contents_xml(app_name, combined_paths)
        else:
            context["file_contents"] = ""
    else:
        context["file_contents"] = ""

    return context


def get_applicable_asvs_keys(asset_tags: List[str]) -> List[str]:
    """Return every ASVS chapter key whose target_assets overlap with *asset_tags*."""
    matrix = _load_json(ASVS_ASSET_RELATION_FILE)["asvs_routing_matrix"]
    tag_set = set(asset_tags)
    return [
        key
        for key, meta in matrix.items()
        if tag_set & set(meta.get("target_assets", []))
    ]


def get_recommended_and_unrecommended_chapters(asset_tags: List[str]) -> tuple[List[str], List[str]]:
    """Separate ASVS chapters into recommended and unrecommended for given asset_tags.

    Returns:
        (recommended_keys, unrecommended_keys) where recommended are those with
        target_assets overlapping asset_tags, and unrecommended are the rest.
    """
    matrix = _load_json(ASVS_ASSET_RELATION_FILE)["asvs_routing_matrix"]
    tag_set = set(asset_tags)

    recommended = []
    unrecommended = []

    for key, meta in matrix.items():
        if tag_set & set(meta.get("target_assets", [])):
            recommended.append(key)
        else:
            unrecommended.append(key)

    return recommended, unrecommended


def build_filtered_static_context(
    app_name: str,
    component_id: str,
    asset_tags: List[str] | None = None,
) -> str:
    """Build filtered static_context XML for a component using its paths and asset-tag scope."""
    component_entry = _get_component_index_entry(app_name, component_id)
    effective_asset_tags = asset_tags or component_entry.get("asset_tags", [])
    component_paths, core_paths = _get_component_scope_paths(app_name, component_id)
    report_names = _report_names_for_asset_tags(effective_asset_tags)
    return _parse_static_reports(
        _read_static_xml(app_name),
        report_names,
        component_paths=component_paths,
        core_paths=core_paths,
    )
