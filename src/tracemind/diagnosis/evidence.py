"""Evidence, hypothesis, tool-call, and run-result models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from tracemind.diagnosis.state import RuntimeEvent, RuntimeState, StopReason
from tracemind.indexing.java_index import SourceMatch


class Evidence(BaseModel):
    """A reviewable fact collected during a diagnosis run."""

    evidence_id: str
    kind: str
    claim: str
    source_ref: str
    supports: list[str] = Field(default_factory=list)
    strength: str = "strong"
    tool_call_id: str | None = None
    created_at: str


class Hypothesis(BaseModel):
    """A root-cause candidate evaluated by deterministic evidence coverage."""

    hypothesis_id: str
    statement: str
    status: str = "candidate"
    evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    source_matches: list[SourceMatch] = Field(default_factory=list)


class ToolCallRecord(BaseModel):
    """Audit-friendly record of one tool call made by the runtime."""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    error_code: str | None = None
    duration_ms: int = 0
    evidence_ids: list[str] = Field(default_factory=list)


class RunResult(BaseModel):
    """The complete in-memory result of one diagnosis run."""

    incident_id: str
    run_id: str
    service: str
    state: RuntimeState
    stop_reason: StopReason
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    budget_usage: dict[str, int] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    events: list[RuntimeEvent] = Field(default_factory=list)
