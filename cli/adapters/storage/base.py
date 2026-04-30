"""Storage adapter interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from cli.models import AuditOutput, ComponentIndex, ComponentItem


class StorageAdapter(ABC):
    """Abstract interface for persistence operations."""

    @abstractmethod
    def write_component_index(self, app_name: str, index: ComponentIndex) -> Path:
        """Persist component index."""

    @abstractmethod
    def write_component_context(self, app_name: str, component_id: str, content: str) -> Path:
        """Write component context (xml/yaml/md based on format)."""

    @abstractmethod
    def write_audit_result(
        self,
        app_name: str,
        component_id: str,
        asvs_key: str,
        result: AuditOutput,
    ) -> Path:
        """Persist audit result (XML + JSON sibling)."""

    @abstractmethod
    def read_component_context(self, app_name: str, component_id: str, format_hint: str | None = None) -> str:
        """Read component context honoring format preference."""

    @abstractmethod
    def read_static_context(self, app_name: str, format_hint: str | None = None) -> str:
        """Read static context (xml/yaml)."""

    @abstractmethod
    def load_component_index(self, app_name: str) -> ComponentIndex:
        """Load component index."""

    @abstractmethod
    def list_components(self, app_name: str) -> list[ComponentItem]:
        """List all components for an app."""

    @abstractmethod
    def component_exists(self, app_name: str, component_id: str) -> bool:
        """Check if component exists."""

    @abstractmethod
    def analysis_exists(self, app_name: str, component_id: str, chapter_id: str) -> bool:
        """Check if analysis file exists."""
