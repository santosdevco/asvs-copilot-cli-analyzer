from __future__ import annotations
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
