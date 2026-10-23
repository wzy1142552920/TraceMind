"""Shared builders for deterministic evaluator tests."""

from __future__ import annotations

from tracemind.diagnosis.evidence import (
    AssessmentVerdict,
    Evidence,
    EvidenceAssessment,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceRequirement,
    Hypothesis,
)

THREAD = "http-a"
THREAD_REF = f"log://incident.log#thread={THREAD}&L1-L3"
BASIS_ID = "ev_basis"


def requirement(
    requirement_id: str,
    kind: EvidenceKind,
    *,
    discriminating: bool = True,
) -> EvidenceRequirement:
    return EvidenceRequirement(
        requirement_id=requirement_id,
        description=f"evidence of kind {kind.value}",
        evidence_kinds=[kind],
        discriminating=discriminating,
    )


def hypothesis(
    hypothesis_id: str,
    requirements: list[EvidenceRequirement],
    *,
    basis_id: str = BASIS_ID,
) -> Hypothesis:
    return Hypothesis(
        hypothesis_id=hypothesis_id,
        statement=f"mechanism for {hypothesis_id}",
        cause_chain=["symptom observed", "mechanism identified"],
        basis_evidence_ids=[basis_id],
        requirements=requirements,
        falsifiers=["the mechanism is contradicted"],
    )


def evidence(
    evidence_id: str,
    kind: EvidenceKind,
    *,
    bound_hypothesis: str,
    bound_requirement: str,
    source_ref: str | None = None,
    tool_call_id: str = "call_1",
    content: dict[str, object] | None = None,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        claim=f"{kind.value} claim",
        source_ref=source_ref or f"artifact://snapshot#L{len(evidence_id)}",
        provenance=EvidenceProvenance.TOOL,
        tool_call_id=tool_call_id,
        observed_at="2026-10-23T00:00:00+00:00",
        bound_hypothesis_id=bound_hypothesis,
        bound_requirement_id=bound_requirement,
        content=content or {},
    )


def assessment(
    assessment_id: str,
    hypothesis_id: str,
    requirement_id: str,
    evidence_id: str,
    verdict: AssessmentVerdict = AssessmentVerdict.SUPPORTS,
) -> EvidenceAssessment:
    return EvidenceAssessment(
        assessment_id=assessment_id,
        hypothesis_id=hypothesis_id,
        requirement_id=requirement_id,
        evidence_id=evidence_id,
        verdict=verdict,
        rationale="structured evidence check",
        created_at="2026-10-23T00:00:00+00:00",
    )


def basis_evidence() -> Evidence:
    return Evidence(
        evidence_id=BASIS_ID,
        kind=EvidenceKind.LOG_EVENT,
        claim="primary event",
        source_ref="log://evt_0001",
        provenance=EvidenceProvenance.LOG_PARSER,
        observed_at="2026-10-23T00:00:00+00:00",
    )
