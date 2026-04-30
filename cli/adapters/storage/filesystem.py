"""Filesystem storage adapter - current behavior."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from cli.adapters.storage.base import StorageAdapter
from cli.config import OUTPUTS_DIR, CONTEXT_FORMAT
from cli.models import AuditOutput, ComponentIndex, ComponentItem


class FilesystemStorage(StorageAdapter):
    """Disk-based storage implementation."""

    def __init__(self, base_dir: Path = OUTPUTS_DIR):
        self.base_dir = base_dir

    def _components_dir(self, app_name: str) -> Path:
        return self.base_dir / app_name / "components"

    def _component_dir(self, app_name: str, component_id: str) -> Path:
        return self._components_dir(app_name) / component_id

    def _analysis_dir(self, app_name: str, component_id: str) -> Path:
        return self._component_dir(app_name, component_id) / "analysis"

    def write_component_index(self, app_name: str, index: ComponentIndex) -> Path:
        dest = self._components_dir(app_name) / "index.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(index.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
        return dest

    def write_component_context(self, app_name: str, component_id: str, content: str) -> Path:
        """Write context with format-appropriate extension."""
        format_pref = CONTEXT_FORMAT or "auto"

        if format_pref in ("yaml", "yml"):
            ext = "yaml"
        elif format_pref == "md":
            ext = "md"
        else:
            ext = "xml"

        dest = self._component_dir(app_name, component_id) / f"context.{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        return dest

    def write_audit_result(
        self,
        app_name: str,
        component_id: str,
        asvs_key: str,
        result: AuditOutput,
    ) -> Path:
        analysis_dir = self._analysis_dir(app_name, component_id)
        analysis_dir.mkdir(parents=True, exist_ok=True)

        chapter_id = asvs_key.split("_")[0]
        dest_xml = analysis_dir / f"{chapter_id}.xml"
        dest_xml.write_text(self._audit_to_xml(result, component_id, chapter_id), encoding="utf-8")

        json_payload = result.model_dump(mode="json", exclude_none=True)
        json_payload["llm_model"] = self._current_llm_model()
        dest_json = analysis_dir / f"{chapter_id}.json"
        dest_json.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        return dest_xml

    def read_component_context(self, app_name: str, component_id: str, format_hint: str | None = None) -> str:
        component_dir = self._component_dir(app_name, component_id)
        preferred = format_hint or CONTEXT_FORMAT or "auto"

        paths_to_try = []
        if preferred == "xml":
            paths_to_try = [component_dir / "context.xml"]
        elif preferred == "md":
            paths_to_try = [component_dir / "context.md"]
        elif preferred in ("yaml", "yml"):
            paths_to_try = [component_dir / "context.yaml", component_dir / "context.yml"]
        else:  # auto
            paths_to_try = [
                component_dir / "context.xml",
                component_dir / "context.yaml",
                component_dir / "context.yml",
                component_dir / "context.md",
            ]

        for path in paths_to_try:
            if path.exists():
                return path.read_text(encoding="utf-8")
        return ""

    def read_static_context(self, app_name: str, format_hint: str | None = None) -> str:
        preferred = format_hint or CONTEXT_FORMAT or "auto"

        if preferred in ("yaml", "yml"):
            path = self.base_dir / app_name / "static_context.yaml"
            if path.exists():
                return path.read_text(encoding="utf-8")

        path = self.base_dir / app_name / "static_context.xml"
        if not path.exists():
            raise FileNotFoundError(f"Static context not found at {path}")
        return path.read_text(encoding="utf-8")

    def load_component_index(self, app_name: str) -> ComponentIndex:
        path = self._components_dir(app_name) / "index.json"
        if not path.exists():
            raise FileNotFoundError(f"Component index not found at {path}. Run `triage` first.")
        return ComponentIndex.model_validate_json(path.read_text(encoding="utf-8"))

    def list_components(self, app_name: str) -> list[ComponentItem]:
        index = self.load_component_index(app_name)
        return index.project_triage

    def component_exists(self, app_name: str, component_id: str) -> bool:
        return self._component_dir(app_name, component_id).exists()

    def analysis_exists(self, app_name: str, component_id: str, chapter_id: str) -> bool:
        analysis_dir = self._analysis_dir(app_name, component_id)
        return (analysis_dir / f"{chapter_id}.xml").exists() or (analysis_dir / f"{chapter_id}.json").exists()

    def _audit_to_xml(self, result: AuditOutput, component_id: str, chapter_id: str) -> str:
        """Serialize AuditOutput to XML format."""
        lines = ["<audit_result>"]
        lines.append(f"  <component_id>{xml_escape(component_id)}</component_id>")
        lines.append(f"  <asvs_chapter>{xml_escape(chapter_id)}</asvs_chapter>")
        lines.append(f"  <audit_date>{date.today().isoformat()}</audit_date>")

        passed = sum(1 for r in result.audit_results if r.status == "PASS")
        failed = sum(1 for r in result.audit_results if r.status == "FAIL")
        na = sum(1 for r in result.audit_results if r.status == "NOT_APPLICABLE")
        lines.append(f'  <summary passed="{passed}" failed="{failed}" not_applicable="{na}" />')

        lines.append("  <requirements>")
        for req in result.audit_results:
            sev = f' severity="{xml_escape(req.severity)}"' if req.severity else ""
            lines.append(f'    <requirement id="{xml_escape(req.requirement_id)}" status="{xml_escape(req.status)}"{sev}>')
            if req.vulnerability_title:
                lines.append(f"      <vulnerability_title>{xml_escape(req.vulnerability_title)}</vulnerability_title>")
            if req.description:
                lines.append(f"      <description>{xml_escape(req.description)}</description>")
            if req.affected_file:
                lines.append(f"      <affected_file>{xml_escape(req.affected_file)}</affected_file>")
            if req.affected_function:
                lines.append(f"      <affected_function>{xml_escape(req.affected_function)}</affected_function>")
            if req.line_range:
                lines.append(f'      <line_range start="{req.line_range[0]}" end="{req.line_range[1]}" />')
            if req.remediation_hint:
                lines.append(f"      <remediation_hint>{xml_escape(req.remediation_hint)}</remediation_hint>")
            lines.append("    </requirement>")
        lines.append("  </requirements>")

        if result.context_update_notes:
            lines.append("  <auditor_diary>")
            for note in result.context_update_notes:
                lines.append(f"    <finding>{xml_escape(note)}</finding>")
            lines.append("  </auditor_diary>")

        lines.append("</audit_result>")
        return "\n".join(lines)

    def _current_llm_model(self) -> str | None:
        """Best-effort resolve of current LLM model."""
        try:
            from cli.adapters.llm import get_current_model
            return get_current_model()
        except Exception:
            return None
