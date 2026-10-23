"""Shared builders for report 0.4 unit tests."""

from __future__ import annotations

from tracemind.artifacts import ArtifactKind, ArtifactRecord
from tracemind.diagnosis.evidence import (
    EvaluationResult,
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
    Hypothesis,
    HypothesisEvaluation,
    HypothesisStatus,
    RunResult,
)
from tracemind.diagnosis.state import RuntimeState, StopReason

OBSERVED_AT = "2026-10-23T00:00:00+00:00"
REPO_SOURCE_REF = (
    "repo://src/main/java/com/example/order/OrderService.java#L17-L27"
)
LOG_EVENT_REF = "log://evt_0003"


def artifact_record(
    artifact_id: str,
    kind: ArtifactKind | str,
    *,
    source_name: str | None = None,
    line_count: int = 5,
    byte_size: int = 100,
    truncated: bool = False,
    warnings: list[str] | None = None,
) -> ArtifactRecord:
    """Build one artifact record with deterministic defaults."""
    return ArtifactRecord(
        artifact_id=artifact_id,
        kind=ArtifactKind(kind),
        source_name=source_name or f"{artifact_id}.txt",
        line_count=line_count,
        byte_size=byte_size,
        truncated=truncated,
        warnings=list(warnings or []),
    )


def evidence(
    evidence_id: str,
    kind: EvidenceKind | str,
    source_ref: str,
    *,
    provenance: EvidenceProvenance | str = EvidenceProvenance.USER_ARTIFACT,
    content: dict | None = None,
) -> Evidence:
    """Build one strong evidence item for report tests."""
    return Evidence(
        evidence_id=evidence_id,
        kind=EvidenceKind(kind),
        claim=f"Evidence {evidence_id}",
        source_ref=source_ref,
        strength="strong",
        provenance=EvidenceProvenance(provenance),
        observed_at=OBSERVED_AT,
        content=content or {},
    )


def run_with(
    evidence_items: list[Evidence],
    *,
    artifacts: list[ArtifactRecord] | None = None,
    status: HypothesisStatus = HypothesisStatus.CONFIRMED,
    limitations: list[str] | None = None,
) -> RunResult:
    """Build a one-hypothesis run result from the supplied evidence."""
    cited = [item.evidence_id for item in evidence_items]
    hypothesis = Hypothesis(
        hypothesis_id="hyp_001",
        statement="The JVM snapshot and source identify the root cause",
        status=status,
        basis_evidence_ids=cited,
        evidence_ids=cited,
        ranking_score=5,
    )
    evaluation = EvaluationResult(
        hypotheses=[
            HypothesisEvaluation(
                hypothesis_id="hyp_001",
                status=status,
                qualifies=status in {
                    HypothesisStatus.CONFIRMED,
                    HypothesisStatus.SUPPORTED,
                },
                supporting_evidence_ids=cited,
                ranking_score=5,
            )
        ],
        top_hypothesis_id="hyp_001",
        run_confirmed=status is HypothesisStatus.CONFIRMED,
    )
    return RunResult(
        incident_id="inc_test",
        run_id="run_test",
        service="order-service",
        state=RuntimeState.COMPLETED,
        stop_reason=StopReason.EVIDENCE_SUFFICIENT,
        hypotheses=[hypothesis],
        evidence=evidence_items,
        evaluation=evaluation,
        artifacts=list(artifacts or []),
        budget_usage={"iterations": 2, "llm_calls": 2, "tool_calls": 2},
        limitations=list(limitations or []),
        events=[],
    )
