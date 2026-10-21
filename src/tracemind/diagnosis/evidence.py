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


class LLMCallRecord(BaseModel):
    """Per-call LLM provenance, latency, and usage."""

    llm_call_id: str
    round: int
    provider: str
    model: str
    request_id: str | None = None
    started_at: str
    latency_ms: int = 0
    attempts: int = 1
    ok: bool = True
    finish_reason: str | None = None
    tool_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    error_code: str | None = None


class LLMUsageSummary(BaseModel):
    """Aggregated LLM usage for one run."""

    calls: int = 0
    failed_calls: int = 0
    retries: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int = 0


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
    llm_calls: list[LLMCallRecord] = Field(default_factory=list)
    llm_usage: LLMUsageSummary = Field(default_factory=LLMUsageSummary)
    budget_usage: dict[str, int] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    events: list[RuntimeEvent] = Field(default_factory=list)


def summarize_llm_usage(records: list[LLMCallRecord]) -> LLMUsageSummary:
    """Aggregate per-call records without inventing unavailable values."""
    calls = len(records)
    failed_calls = sum(1 for record in records if not record.ok)
    retries = sum(max(0, record.attempts - 1) for record in records)
    latency_ms = sum(record.latency_ms for record in records)

    def total(attribute: str) -> int | None:
        values = [
            getattr(record, attribute)
            for record in records
            if getattr(record, attribute) is not None
        ]
        return sum(values) if values else None

    input_tokens = total("input_tokens")
    output_tokens = total("output_tokens")
    total_tokens = total("total_tokens")
    if (
        total_tokens is None
        and input_tokens is not None
        and output_tokens is not None
    ):
        total_tokens = input_tokens + output_tokens

    return LLMUsageSummary(
        calls=calls,
        failed_calls=failed_calls,
        retries=retries,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
    )
