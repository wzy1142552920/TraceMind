"""Evidence, hypothesis, assessment, tool-call, and run-result models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from tracemind.artifacts.models import ArtifactRecord
from tracemind.diagnosis.state import RuntimeEvent, RuntimeState, StopReason


class EvidenceKind(StrEnum):
    """Structured evidence categories accepted by the v0.3 ledger."""

    LOG_EVENT = "log_event"
    LOG_THREAD_CONTEXT = "log_thread_context"
    STACK_FRAME = "stack_frame"
    SOURCE_CODE = "source_code"
    CALL_PATH = "call_path"
    SQL = "sql"
    ANNOTATION = "annotation"
    CONFIG = "config"
    DB_ROW = "db_row"
    DB_SCHEMA = "db_schema"
    THREAD_DUMP = "thread_dump"
    THREAD_CPU = "thread_cpu"
    GC_EVENT = "gc_event"
    GC_SUMMARY = "gc_summary"
    HEAP_SUMMARY = "heap_summary"


class EvidenceProvenance(StrEnum):
    """Where an evidence item originally came from."""

    LOG_PARSER = "log_parser"
    AST_INDEX = "ast_index"
    TOOL = "tool"
    FAKE_VERIFICATION = "fake_verification"
    USER_ARTIFACT = "user_artifact"


class HypothesisStatus(StrEnum):
    """Deterministic status assigned to a root-cause hypothesis."""

    CANDIDATE = "candidate"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    CONFIRMED = "confirmed"
    INSUFFICIENT_DATA = "insufficient_data"


class AssessmentVerdict(StrEnum):
    """How a real evidence item affects one hypothesis requirement."""

    SUPPORTS = "supports"
    REFUTES = "refutes"
    NEUTRAL = "neutral"


class EvidenceBinding(BaseModel):
    """One hypothesis requirement this evidence item was obtained for."""

    hypothesis_id: str
    requirement_id: str
    tool_call_id: str | None = None


class Evidence(BaseModel):
    """A reviewable fact collected during a diagnosis run."""

    evidence_id: str
    kind: EvidenceKind
    claim: str
    source_ref: str
    strength: Literal["strong", "medium", "weak"] = "strong"
    provenance: EvidenceProvenance
    tool_call_id: str | None = None
    observed_at: str
    independence_group: str | None = None
    bound_hypothesis_id: str | None = None
    bound_requirement_id: str | None = None
    bindings: list[EvidenceBinding] = Field(default_factory=list)
    content: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _derive_groups(self) -> Self:
        if self.independence_group is None:
            self.independence_group = f"{self.kind}:{self.source_ref}"
        if self.bound_requirement_id is not None and self.bound_hypothesis_id is None:
            raise ValueError("bound_requirement_id requires bound_hypothesis_id")
        if (
            self.bound_hypothesis_id is not None
            and self.bound_requirement_id is not None
            and not self.has_binding(
                self.bound_hypothesis_id,
                self.bound_requirement_id,
            )
        ):
            self.bindings = [
                *self.bindings,
                EvidenceBinding(
                    hypothesis_id=self.bound_hypothesis_id,
                    requirement_id=self.bound_requirement_id,
                ),
            ]
        return self

    def has_binding(self, hypothesis_id: str, requirement_id: str) -> bool:
        """Return whether this fact was obtained for a requirement."""
        if (
            self.bound_hypothesis_id == hypothesis_id
            and self.bound_requirement_id == requirement_id
        ):
            return True
        return any(
            binding.hypothesis_id == hypothesis_id
            and binding.requirement_id == requirement_id
            for binding in self.bindings
        )

    def is_bound_to(self, hypothesis_id: str) -> bool:
        """Return whether any requirement of the hypothesis owns this fact."""
        if self.bound_hypothesis_id == hypothesis_id:
            return True
        return any(
            binding.hypothesis_id == hypothesis_id
            for binding in self.bindings
        )

    def add_binding(
        self,
        hypothesis_id: str,
        requirement_id: str,
        tool_call_id: str | None = None,
    ) -> bool:
        """Add another requirement binding; return whether it was new."""
        for binding in self.bindings:
            if (
                binding.hypothesis_id == hypothesis_id
                and binding.requirement_id == requirement_id
            ):
                if binding.tool_call_id is None and tool_call_id is not None:
                    binding.tool_call_id = tool_call_id
                return False
        self.bindings.append(
            EvidenceBinding(
                hypothesis_id=hypothesis_id,
                requirement_id=requirement_id,
                tool_call_id=tool_call_id,
            )
        )
        return True


class EvidenceRequirement(BaseModel):
    """A verification requirement declared by an LLM hypothesis."""

    requirement_id: str
    description: str
    evidence_kinds: list[EvidenceKind]
    discriminating: bool
    suggested_tools: list[str] = Field(default_factory=list)


class Hypothesis(BaseModel):
    """A root-cause candidate evaluated by deterministic evidence coverage."""

    hypothesis_id: str
    statement: str
    cause_chain: list[str] = Field(default_factory=list)
    basis_evidence_ids: list[str] = Field(default_factory=list)
    requirements: list[EvidenceRequirement] = Field(default_factory=list)
    falsifiers: list[str] = Field(default_factory=list)
    status: HypothesisStatus = HypothesisStatus.CANDIDATE
    evidence_ids: list[str] = Field(default_factory=list)
    assessment_ids: list[str] = Field(default_factory=list)
    missing_requirement_ids: list[str] = Field(default_factory=list)
    ranking_score: int = 0
    source: Literal["llm"] = "llm"


class EvidenceAssessment(BaseModel):
    """An LLM's interpretation of a real, bound evidence item."""

    assessment_id: str
    hypothesis_id: str
    requirement_id: str
    evidence_id: str
    verdict: AssessmentVerdict
    rationale: str
    created_at: str
    revised_at: str | None = None


class RequirementEvaluation(BaseModel):
    """Deterministic coverage result for one requirement."""

    requirement_id: str
    satisfied: bool
    discriminating: bool = False
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    refuting_evidence_ids: list[str] = Field(default_factory=list)


class HypothesisEvaluation(BaseModel):
    """Deterministic result for one hypothesis."""

    hypothesis_id: str
    status: HypothesisStatus
    qualifies: bool
    requirements: list[RequirementEvaluation] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    refuting_evidence_ids: list[str] = Field(default_factory=list)
    missing_requirement_ids: list[str] = Field(default_factory=list)
    ranking_score: int = 0
    reasons: list[str] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    """Run-level deterministic evaluation result."""

    hypotheses: list[HypothesisEvaluation] = Field(default_factory=list)
    top_hypothesis_id: str | None = None
    run_confirmed: bool = False
    ambiguity: bool = False

    def for_hypothesis(self, hypothesis_id: str) -> HypothesisEvaluation | None:
        """Return the evaluation entry for one hypothesis, if present."""
        return next(
            (
                item
                for item in self.hypotheses
                if item.hypothesis_id == hypothesis_id
            ),
            None,
        )


class RejectedHypothesis(BaseModel):
    """A grounded-hypothesis proposal rejected by the runtime protocol."""

    statement: str
    reason: str
    error_code: str | None = None
    tool_call_id: str | None = None
    observed_at: str


class RemediationAction(BaseModel):
    """A deterministic, evidence-bound remediation suggestion."""

    action_id: str
    hypothesis_id: str
    type: Literal["code", "config", "data", "ops", "test"]
    title: str
    description: str
    evidence_ids: list[str] = Field(default_factory=list)
    target: str
    risk: str
    prerequisites: list[str] = Field(default_factory=list)
    verification_steps: list[str] = Field(default_factory=list)


class RejectedRemediation(BaseModel):
    """A remediation action dropped by deterministic validation."""

    hypothesis_id: str | None = None
    title: str | None = None
    error_code: str = "INVALID_REMEDIATION"
    reason: str
    tool_call_id: str | None = None
    observed_at: str


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
    assessments: list[EvidenceAssessment] = Field(default_factory=list)
    rejected_hypotheses: list[RejectedHypothesis] = Field(default_factory=list)
    evaluation: EvaluationResult = Field(default_factory=EvaluationResult)
    remediation_actions: list[RemediationAction] = Field(default_factory=list)
    rejected_remediations: list[RejectedRemediation] = Field(
        default_factory=list
    )
    verification_environment: str | None = None
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
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
