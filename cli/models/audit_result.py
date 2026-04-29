from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field


class AuditResultItem(BaseModel):
    requirement_id: str
    status: str                                      # PASS | FAIL | NOT_APPLICABLE
    severity: Optional[str] = None                   # CRITICAL|HIGH|MEDIUM|LOW|INFO
    vulnerability_title: Optional[str] = None
    description: Optional[str] = None
    affected_file: Optional[str] = None
    affected_function: Optional[str] = None
    line_range: Optional[Tuple[int, int]] = None
    remediation_hint: Optional[str] = None


class AuditOutput(BaseModel):
    component_id: str
    asvs_chapter: str
    audit_results: List[AuditResultItem] = Field(default_factory=list)
    context_update_notes: List[str] = Field(default_factory=list)


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)```")


class GroupedAuditOutput(BaseModel):
    """Wraps multiple AuditOutput objects returned by a single grouped LLM call."""

    results: List[AuditOutput]

    @classmethod
    def parse_grouped(cls, text: str) -> "GroupedAuditOutput":
        """Parse a JSON array of AuditOutput objects from raw LLM response text."""
        match = _JSON_BLOCK_RE.search(text)
        json_text = match.group(1).strip() if match else text.strip()
        data = json.loads(json_text)
        if isinstance(data, list):
            return cls(results=[AuditOutput.model_validate(item) for item in data])
        raise ValueError(f"Expected JSON array at top level, got {type(data).__name__}")
