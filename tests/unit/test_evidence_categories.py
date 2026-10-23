"""Unit tests for symptom/mechanism evidence coverage."""

from __future__ import annotations

from evaluator_helpers import (
    THREAD,
    THREAD_REF,
    assessment,
    basis_evidence,
    evidence,
    hypothesis,
    requirement,
)

from tracemind.diagnosis.evaluator import (
    MECHANISM_KINDS,
    SYMPTOM_KINDS,
    evaluate_hypotheses,
)
from tracemind.diagnosis.evidence import (
    AssessmentVerdict,
    EvidenceKind,
    HypothesisStatus,
)


def test_evidence_kind_sets_match_the_v04_contract() -> None:
    assert SYMPTOM_KINDS == frozenset(
        {
            EvidenceKind.LOG_EVENT,
            EvidenceKind.LOG_THREAD_CONTEXT,
            EvidenceKind.STACK_FRAME,
            EvidenceKind.THREAD_DUMP,
            EvidenceKind.THREAD_CPU,
            EvidenceKind.GC_EVENT,
            EvidenceKind.GC_SUMMARY,
            EvidenceKind.HEAP_SUMMARY,
            EvidenceKind.DB_ROW,
        }
    )
    assert MECHANISM_KINDS == frozenset(
        {
            EvidenceKind.SOURCE_CODE,
            EvidenceKind.CALL_PATH,
            EvidenceKind.SQL,
            EvidenceKind.ANNOTATION,
            EvidenceKind.CONFIG,
            EvidenceKind.DB_SCHEMA,
        }
    )
    assert SYMPTOM_KINDS.isdisjoint(MECHANISM_KINDS)
    assert SYMPTOM_KINDS | MECHANISM_KINDS == set(EvidenceKind)


def _alternatives() -> tuple[list, list, list]:
    """Return target/alternative hypotheses with a refuted alternative."""
    target = hypothesis(
        "hyp_001",
        [
            requirement("hyp_001_req_cpu", EvidenceKind.THREAD_CPU),
            requirement(
                "hyp_001_req_code",
                EvidenceKind.SOURCE_CODE,
                discriminating=False,
            ),
        ],
    )
    alternative = hypothesis(
        "hyp_002",
        [requirement("hyp_002_req_gc", EvidenceKind.GC_SUMMARY)],
    )
    evidence_items = [
        basis_evidence(),
        evidence(
            "ev_cpu",
            EvidenceKind.THREAD_CPU,
            bound_hypothesis="hyp_001",
            bound_requirement="hyp_001_req_cpu",
            source_ref="artifact://thread-cpu#L4",
        ),
        evidence(
            "ev_code",
            EvidenceKind.SOURCE_CODE,
            bound_hypothesis="hyp_001",
            bound_requirement="hyp_001_req_code",
            source_ref="repo://src/OrderService.java#L17-L27",
        ),
        evidence(
            "ev_gc",
            EvidenceKind.GC_SUMMARY,
            bound_hypothesis="hyp_002",
            bound_requirement="hyp_002_req_gc",
            source_ref="artifact://gc-log#L1-L2",
        ),
    ]
    assessments = [
        assessment("asm_1", "hyp_001", "hyp_001_req_cpu", "ev_cpu"),
        assessment("asm_2", "hyp_001", "hyp_001_req_code", "ev_code"),
        assessment(
            "asm_3",
            "hyp_002",
            "hyp_002_req_gc",
            "ev_gc",
            AssessmentVerdict.REFUTES,
        ),
    ]
    return [target, alternative], evidence_items, assessments


def test_complete_symptom_and_mechanism_confirm() -> None:
    hypotheses, evidence_items, assessments = _alternatives()

    result = evaluate_hypotheses(hypotheses, evidence_items, assessments)

    target = result.for_hypothesis("hyp_001")
    assert target is not None
    assert target.status is HypothesisStatus.CONFIRMED
    assert target.qualifies is True
    assert not any(
        reason.startswith("missing_symptom_evidence")
        or reason.startswith("missing_mechanism_evidence")
        for reason in target.reasons
    )
    assert result.run_confirmed is True


def test_symptom_only_is_supported_with_mechanism_warning() -> None:
    target = hypothesis(
        "hyp_001",
        [requirement("hyp_001_req_cpu", EvidenceKind.THREAD_CPU)],
    )
    alternative = hypothesis(
        "hyp_002",
        [requirement("hyp_002_req_gc", EvidenceKind.GC_SUMMARY)],
    )
    evidence_items = [
        basis_evidence(),
        evidence(
            "ev_cpu",
            EvidenceKind.THREAD_CPU,
            bound_hypothesis="hyp_001",
            bound_requirement="hyp_001_req_cpu",
            source_ref="artifact://thread-cpu#L4",
        ),
        evidence(
            "ev_gc",
            EvidenceKind.GC_SUMMARY,
            bound_hypothesis="hyp_002",
            bound_requirement="hyp_002_req_gc",
            source_ref="artifact://gc-log#L1-L2",
        ),
    ]
    assessments = [
        assessment("asm_1", "hyp_001", "hyp_001_req_cpu", "ev_cpu"),
        assessment(
            "asm_2",
            "hyp_002",
            "hyp_002_req_gc",
            "ev_gc",
            AssessmentVerdict.REFUTES,
        ),
    ]

    result = evaluate_hypotheses([target, alternative], evidence_items, assessments)

    evaluation = result.for_hypothesis("hyp_001")
    assert evaluation is not None
    assert evaluation.status is HypothesisStatus.SUPPORTED
    assert evaluation.qualifies is False
    assert any(
        reason.startswith("missing_mechanism_evidence:")
        for reason in evaluation.reasons
    )
    assert not any(
        reason.startswith("missing_symptom_evidence")
        for reason in evaluation.reasons
    )
    assert result.run_confirmed is False


def test_mechanism_only_is_supported_with_symptom_warning() -> None:
    target = hypothesis(
        "hyp_001",
        [requirement("hyp_001_req_code", EvidenceKind.SOURCE_CODE)],
    )
    alternative = hypothesis(
        "hyp_002",
        [requirement("hyp_002_req_db", EvidenceKind.DB_ROW)],
    )
    evidence_items = [
        basis_evidence(),
        evidence(
            "ev_code",
            EvidenceKind.SOURCE_CODE,
            bound_hypothesis="hyp_001",
            bound_requirement="hyp_001_req_code",
            source_ref="repo://src/OrderService.java#L17-L27",
        ),
        evidence(
            "ev_db",
            EvidenceKind.DB_ROW,
            bound_hypothesis="hyp_002",
            bound_requirement="hyp_002_req_db",
            source_ref="db://orders/id=10086",
        ),
    ]
    assessments = [
        assessment("asm_1", "hyp_001", "hyp_001_req_code", "ev_code"),
        assessment(
            "asm_2",
            "hyp_002",
            "hyp_002_req_db",
            "ev_db",
            AssessmentVerdict.REFUTES,
        ),
    ]

    result = evaluate_hypotheses([target, alternative], evidence_items, assessments)

    evaluation = result.for_hypothesis("hyp_001")
    assert evaluation is not None
    assert evaluation.status is HypothesisStatus.SUPPORTED
    assert evaluation.qualifies is False
    assert any(
        reason.startswith("missing_symptom_evidence:")
        for reason in evaluation.reasons
    )
    assert result.run_confirmed is False


def test_legacy_log_code_and_db_evidence_still_confirm() -> None:
    target = hypothesis(
        "hyp_001",
        [
            requirement("hyp_001_req_ctx", EvidenceKind.LOG_THREAD_CONTEXT),
            requirement(
                "hyp_001_req_sql",
                EvidenceKind.SQL,
                discriminating=False,
            ),
        ],
    )
    alternative = hypothesis(
        "hyp_002",
        [requirement("hyp_002_req_db", EvidenceKind.DB_ROW)],
    )
    evidence_items = [
        basis_evidence(),
        evidence(
            "ev_ctx",
            EvidenceKind.LOG_THREAD_CONTEXT,
            bound_hypothesis="hyp_001",
            bound_requirement="hyp_001_req_ctx",
            source_ref=THREAD_REF,
            content={"thread": THREAD},
        ),
        evidence(
            "ev_sql",
            EvidenceKind.SQL,
            bound_hypothesis="hyp_001",
            bound_requirement="hyp_001_req_sql",
            source_ref="repo://src/OrderMapper.java#L16",
        ),
        evidence(
            "ev_db",
            EvidenceKind.DB_ROW,
            bound_hypothesis="hyp_002",
            bound_requirement="hyp_002_req_db",
            source_ref="db://orders/id=10086",
        ),
    ]
    assessments = [
        assessment("asm_1", "hyp_001", "hyp_001_req_ctx", "ev_ctx"),
        assessment("asm_2", "hyp_001", "hyp_001_req_sql", "ev_sql"),
        assessment(
            "asm_3",
            "hyp_002",
            "hyp_002_req_db",
            "ev_db",
            AssessmentVerdict.REFUTES,
        ),
    ]

    result = evaluate_hypotheses(
        [target, alternative],
        evidence_items,
        assessments,
        require_log_thread_context=True,
        required_log_thread=THREAD,
    )

    evaluation = result.for_hypothesis("hyp_001")
    assert evaluation is not None
    assert evaluation.status is HypothesisStatus.CONFIRMED
    assert evaluation.qualifies is True
    assert result.run_confirmed is True
