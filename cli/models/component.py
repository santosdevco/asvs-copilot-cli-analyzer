from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SemanticContext(BaseModel):
    architectural_role: str
    data_inputs: List[str] = Field(default_factory=list)
    data_outputs: List[str] = Field(default_factory=list)
    state_management: str = ""
    external_interactions: List[str] = Field(default_factory=list)


class ComponentItem(BaseModel):
    component_id: str
    component_name: str
    risk_level: str                           # CRITICAL | HIGH | MEDIUM | LOW
    asset_tags: List[str] = Field(default_factory=list)
    files_to_audit: List[str] = Field(default_factory=list)
    initial_semantic_context: SemanticContext


class ComponentIndex(BaseModel):
    project_triage: List[ComponentItem] = Field(default_factory=list)
