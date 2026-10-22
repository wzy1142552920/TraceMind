"""Unit tests for the v0.3 differential-diagnosis report."""

from __future__ import annotations

from pathlib import Path

from tracemind.diagnosis.evidence import (
    EvaluationResult,
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceRequirement,
    Hypothesis,
    HypothesisEvaluation,
    HypothesisStatus,
    RejectedRemediation,
    RemediationAction,
    RequirementEvaluation,
    RunResult,
)
from tracemind.diagnosis.report import (
    build_report,
    render_markdown,
    validate_report,
)
from tracemind.diagnosis.state import RuntimeState, StopReason
from tracemind.log_analysis.parser import LogParser

LOG_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "logs" / "basic" / "incident.log"
)
REPO_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "repos"
    / "minimal-order-service"
)
CREATED_AT = "2026-10-22T00:00:00+00:00"
CODE_TARGET = "src/main/java/com/example/order/OrderService.java"
CODE_REF = f"repo://{CODE_TARGET}#L17-L27"
THREAD_REF = "log://incident.log#thread=http-nio-8080-exec-7&L1-L3"


def _evidence(
    evidence_id: str,
    kind: EvidenceKind,
    source_ref: str,
    *,
    provenance: EvidenceProvenance = EvidenceProvenance.TOOL,
    content: dict | None = None,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        claim=f"Evidence {evidence_id}",
        source_ref=source_ref,
        strength="strong",
        provenance=provenance,
        observed_at=CREATED_AT,
        content=content or {},
    )


def _result(
    *,
    status: HypothesisStatus = HypothesisStatus.CONFIRMED,
    with_db: bool = False,
    remediation: list[RemediationAction] | None = None,
) -> RunResult:
    evidence = [
        _evidence(
            "ev_0001",
            EvidenceKind.LOG_THREAD_CONTEXT,
            THREAD_REF,
            provenance=EvidenceProvenance.LOG_PARSER,
            content={
                "thread": "http-nio-8080-exec-7",
                "line_start": 1,
                "line_end": 3,
                "items": [
                    {"message": "paid callback orderId=10086"},
                    {"message": "updateStatus returned rows=0"},
                    {"message": "failed to update order status"},
                ],
            },
        ),
        _evidence(
            "ev_0002",
            EvidenceKind.SOURCE_CODE,
            CODE_REF,
            content={"file_path": CODE_TARGET},
        ),
    ]
    if with_db:
        evidence.append(
            _evidence(
                "ev_0003",
                EvidenceKind.DB_ROW,
                "db://orders/id=10086",
                provenance=EvidenceProvenance.FAKE_VERIFICATION,
                content={
                    "table": "orders",
                    "environment": "fixture",
                    "found": False,
                },
            )
        )
    hypothesis = Hypothesis(
        hypothesis_id="hyp_001",
        statement="The order row is missing when the PAID callback is handled",
        cause_chain=["Callback arrives", "Mapper returns rows=0", "Service throws"],
        status=status,
        basis_evidence_ids=["ev_0001", "ev_0002"],
        evidence_ids=[item.evidence_id for item in evidence],
        requirements=[
            EvidenceRequirement(
                requirement_id="hyp_001_req_01",
                description="Rows are absent",
                evidence_kinds=[EvidenceKind.DB_ROW],
                discriminating=True,
            ),
        ],
        falsifiers=["The order row exists and is already PAID."],
        ranking_score=9,
    )
    alternative = Hypothesis(
        hypothesis_id="hyp_002",
        statement="The UPDATE ignores the order id",
        status=HypothesisStatus.CONTRADICTED,
        basis_evidence_ids=["ev_0002"],
        ranking_score=-4,
        falsifiers=["The UPDATE constrains the order id."],
    )
    confirmed = status is HypothesisStatus.CONFIRMED
    evaluation = EvaluationResult(
        hypotheses=[
            HypothesisEvaluation(
                hypothesis_id="hyp_001",
                status=status,
                qualifies=status in {HypothesisStatus.CONFIRMED, HypothesisStatus.SUPPORTED},
                requirements=[
                    RequirementEvaluation(
                        requirement_id="hyp_001_req_01",
                        satisfied=confirmed,
                        discriminating=True,
                        supporting_evidence_ids=["ev_0002"],
                    )
                ],
                supporting_evidence_ids=["ev_0001", "ev_0002"],
                ranking_score=9,
            ),
            HypothesisEvaluation(
                hypothesis_id="hyp_002",
                status=HypothesisStatus.CONTRADICTED,
                qualifies=False,
                refuting_evidence_ids=["ev_0002"],
                ranking_score=-4,
            ),
        ],
        top_hypothesis_id="hyp_001",
        run_confirmed=confirmed,
    )
    return RunResult(
        incident_id="inc_test",
        run_id="run_test",
        service="order-service",
        state=(
            RuntimeState.COMPLETED
            if confirmed
            else RuntimeState.INSUFFICIENT_DATA
        ),
        stop_reason=(
            StopReason.EVIDENCE_SUFFICIENT
            if confirmed
            else StopReason.NO_PROGRESS
        ),
        hypotheses=[hypothesis, alternative],
        evidence=evidence,
        evaluation=evaluation,
        remediation_actions=remediation or [],
        budget_usage={"iterations": 3, "llm_calls": 3, "tool_calls": 7},
    )


def _action(
    hypothesis_id: str = "hyp_001",
    evidence_ids: list[str] | None = None,
) -> RemediationAction:
    return RemediationAction(
        action_id="act_001",
        hypothesis_id=hypothesis_id,
        type="code",
        title="Handle the missing row",
        description="Return an explicit business error when the order is absent.",
        evidence_ids=evidence_ids or ["ev_0002"],
        target=CODE_TARGET,
        risk="Changes caller-visible failure semantics.",
        prerequisites=["Confirm the callback contract."],
        verification_steps=["Add a duplicate-callback test."],
    )


def test_confirmed_report_shape_and_sorting() -> None:
    parsed = LogParser().parse(LOG_FIXTURE)
    report = build_report(_result(remediation=[_action()]), parsed, REPO_FIXTURE)

    assert report.schema_version == "0.3"
    assert report.status == "confirmed"
    assert [item.hypothesis_id for item in report.hypotheses] == [
        "hyp_001",
        "hyp_002",
    ]
    assert report.hypotheses[0].requirements[0].satisfied is True
    assert report.hypotheses[1].status == "contradicted"
    assert report.remediation_plan[0].conditional is False
    assert report.verification.environment == "none"
    assert report.validation.citations_valid is True
    assert report.validation.hypotheses_valid is True
    assert report.validation.remediation_grounded is True
    assert report.validation.verification_labeled is True


def test_supported_hypothesis_remediation_is_conditional() -> None:
    parsed = LogParser().parse(LOG_FIXTURE)
    report = build_report(
        _result(status=HypothesisStatus.SUPPORTED, remediation=[_action()]),
        parsed,
        REPO_FIXTURE,
    )

    assert report.status == "probable"
    assert report.remediation_plan[0].conditional is True
    assert report.status != "confirmed"


def test_fixture_verification_is_labeled() -> None:
    parsed = LogParser().parse(LOG_FIXTURE)
    report = build_report(_result(with_db=True), parsed, REPO_FIXTURE)

    assert report.verification.environment == "fixture"
    assert report.verification.backend == "fake"
    assert report.verification.tables_queried == ["orders"]
    assert "fixture" in report.verification.note.lower()
    assert "fixture" in report.summary.lower()
    assert any("fixture" in item.lower() for item in report.limitations)
    assert report.validation.verification_labeled is True


def test_diagnostic_validation_failure_downgrades_status() -> None:
    parsed = LogParser().parse(LOG_FIXTURE)
    result = _result(remediation=[_action()])
    report = build_report(result, parsed, REPO_FIXTURE)
    report.sources[0].source_ref = "repo://missing/File.java#L1-L2"

    validate_report(report, result, parsed, REPO_FIXTURE)

    assert report.validation.citations_valid is False
    assert report.status == "insufficient_data"
    assert report.validation.hypotheses_valid is True


def test_remediation_failure_does_not_downgrade_status() -> None:
    parsed = LogParser().parse(LOG_FIXTURE)
    result = _result(remediation=[_action(evidence_ids=["ev_missing"])])
    report = build_report(result, parsed, REPO_FIXTURE)

    assert report.status == "confirmed"
    assert report.validation.remediation_grounded is False
    assert report.validation.citations_valid is True
    assert report.validation.evidence_ids_valid is True
    assert report.remediation_plan == []
    assert any(
        "All remediation actions" in item for item in report.limitations
    )


def test_mixed_rejected_attempts_keep_grounded_plan() -> None:
    parsed = LogParser().parse(LOG_FIXTURE)
    result = _result(remediation=[_action()])
    result.rejected_remediations.append(
        RejectedRemediation(
            hypothesis_id="hyp_001",
            title="Duplicate action",
            reason="duplicate remediation action",
            observed_at=CREATED_AT,
        )
    )

    report = build_report(result, parsed, REPO_FIXTURE)

    assert report.remediation_plan
    assert report.validation.remediation_grounded is True
    assert report.validation.errors == []
    assert any(
        "rejected remediation attempt" in item for item in report.limitations
    )


def test_all_rejected_attempts_fail_remediation_grounding() -> None:
    parsed = LogParser().parse(LOG_FIXTURE)
    result = _result(remediation=[])
    result.rejected_remediations.append(
        RejectedRemediation(
            hypothesis_id="hyp_001",
            title="Invalid action",
            reason="evidence is not associated with the hypothesis: ev_9999",
            observed_at=CREATED_AT,
        )
    )

    report = build_report(result, parsed, REPO_FIXTURE)

    assert report.remediation_plan == []
    assert report.validation.remediation_grounded is False
    assert any(
        "all remediation actions were rejected" in error
        for error in report.validation.errors
    )


def test_no_remediation_is_not_fabricated() -> None:
    parsed = LogParser().parse(LOG_FIXTURE)
    report = build_report(
        _result(status=HypothesisStatus.SUPPORTED),
        parsed,
        REPO_FIXTURE,
    )

    assert report.remediation_plan == []
    assert any(
        "No validated remediation action" in item
        for item in report.limitations
    )


def test_markdown_shows_thread_context_and_remediation() -> None:
    parsed = LogParser().parse(LOG_FIXTURE)
    report = build_report(_result(with_db=True, remediation=[_action()]), parsed, REPO_FIXTURE)
    markdown = render_markdown(report)

    assert "## 鉴别诊断" in markdown
    assert "ranking_score" in markdown
    assert "排序分，不是概率" in markdown
    assert "thread=http-nio-8080-exec-7" in markdown
    assert "L1-L3" in markdown
    assert "paid callback orderId=10086" in markdown
    assert "## 验证过程" in markdown
    assert "fixture" in markdown
    assert "## 修复方案" in markdown
    assert "act_001" in markdown
    assert "目标未自动验证" not in markdown
