"""Unit tests for v0.4 evaluator rules around JVM coverage and context."""

from __future__ import annotations

from evaluator_helpers import (
    THREAD,
    assessment,
    basis_evidence,
    evidence,
    hypothesis,
    requirement,
)

from tracemind.diagnosis.evaluator import evaluate_hypotheses
from tracemind.diagnosis.evidence import (
    AssessmentVerdict,
    EvidenceKind,
    HypothesisStatus,
)


def _jvm_scenario(*, refute_target: bool = False):
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
    if refute_target:
        evidence_items.append(
            evidence(
                "ev_cpu_second",
                EvidenceKind.THREAD_CPU,
                bound_hypothesis="hyp_001",
                bound_requirement="hyp_001_req_cpu",
                source_ref="artifact://thread-cpu#L5",
                tool_call_id="call_2",
            )
        )
        assessments.append(
            assessment(
                "asm_4",
                "hyp_001",
                "hyp_001_req_cpu",
                "ev_cpu_second",
                AssessmentVerdict.REFUTES,
            )
        )
    return [target, alternative], evidence_items, assessments


def test_jvm_symptom_and_code_mechanism_confirm_without_log_context() -> None:
    hypotheses, evidence_items, assessments = _jvm_scenario()

    result = evaluate_hypotheses(
        hypotheses,
        evidence_items,
        assessments,
        require_log_thread_context=False,
    )

    target = result.for_hypothesis("hyp_001")
    alternative = result.for_hypothesis("hyp_002")
    assert target is not None and alternative is not None
    assert target.status is HypothesisStatus.CONFIRMED
    assert target.qualifies is True
    assert alternative.status is HypothesisStatus.CONTRADICTED
    assert not any("same-thread" in reason for reason in target.reasons)
    assert result.run_confirmed is True
    assert result.ambiguity is False


def test_jvm_coverage_does_not_bypass_an_enabled_context_gate() -> None:
    hypotheses, evidence_items, assessments = _jvm_scenario()

    result = evaluate_hypotheses(
        hypotheses,
        evidence_items,
        assessments,
        require_log_thread_context=True,
        required_log_thread=THREAD,
    )

    target = result.for_hypothesis("hyp_001")
    assert target is not None
    assert target.qualifies is False
    assert target.status is HypothesisStatus.SUPPORTED
    assert any("same-thread" in reason for reason in target.reasons)
    assert result.run_confirmed is False


def test_refute_still_contradicts_a_fully_covered_hypothesis() -> None:
    hypotheses, evidence_items, assessments = _jvm_scenario(refute_target=True)

    result = evaluate_hypotheses(
        hypotheses,
        evidence_items,
        assessments,
        require_log_thread_context=False,
    )

    target = result.for_hypothesis("hyp_001")
    assert target is not None
    assert target.status is HypothesisStatus.CONTRADICTED
    assert target.qualifies is False
    assert target.refuting_evidence_ids == ["ev_cpu_second"]
    assert result.run_confirmed is False


def test_single_hypothesis_cannot_confirm_even_with_jvm_and_code() -> None:
    hypotheses, evidence_items, assessments = _jvm_scenario()
    hypotheses = [hypotheses[0]]
    assessments = [
        item for item in assessments if item.hypothesis_id == "hyp_001"
    ]

    result = evaluate_hypotheses(
        hypotheses,
        evidence_items,
        assessments,
        require_log_thread_context=False,
    )

    target = result.for_hypothesis("hyp_001")
    assert target is not None
    assert target.qualifies is True
    assert target.status is HypothesisStatus.SUPPORTED
    assert result.run_confirmed is False


def test_open_alternative_prevents_jvm_confirmation() -> None:
    hypotheses, evidence_items, assessments = _jvm_scenario()
    assessments = [
        item for item in assessments if item.hypothesis_id == "hyp_001"
    ]

    result = evaluate_hypotheses(
        hypotheses,
        evidence_items,
        assessments,
        require_log_thread_context=False,
    )

    target = result.for_hypothesis("hyp_001")
    alternative = result.for_hypothesis("hyp_002")
    assert target is not None and alternative is not None
    assert target.qualifies is True
    assert target.status is HypothesisStatus.SUPPORTED
    assert alternative.status is HypothesisStatus.CANDIDATE
    assert result.run_confirmed is False


def test_two_fully_covered_hypotheses_remain_ambiguous() -> None:
    hypotheses, evidence_items, assessments = _jvm_scenario()
    alternative = hypotheses[1]
    alternative.requirements = [
        requirement("hyp_002_req_cpu", EvidenceKind.THREAD_CPU),
        requirement(
            "hyp_002_req_code",
            EvidenceKind.SOURCE_CODE,
            discriminating=False,
        ),
    ]
    evidence_items.extend(
        [
            evidence(
                "ev_cpu_alt",
                EvidenceKind.THREAD_CPU,
                bound_hypothesis="hyp_002",
                bound_requirement="hyp_002_req_cpu",
                source_ref="artifact://thread-cpu#L5",
                tool_call_id="call_2",
            ),
            evidence(
                "ev_code_alt",
                EvidenceKind.SOURCE_CODE,
                bound_hypothesis="hyp_002",
                bound_requirement="hyp_002_req_code",
                source_ref="repo://src/Other.java#L1-L5",
                tool_call_id="call_2",
            ),
        ]
    )
    assessments = [
        item
        for item in assessments
        if item.assessment_id != "asm_3"
    ]
    assessments.extend(
        [
            assessment(
                "asm_4",
                "hyp_002",
                "hyp_002_req_cpu",
                "ev_cpu_alt",
            ),
            assessment(
                "asm_5",
                "hyp_002",
                "hyp_002_req_code",
                "ev_code_alt",
            ),
        ]
    )

    result = evaluate_hypotheses(
        hypotheses,
        evidence_items,
        assessments,
        require_log_thread_context=False,
    )

    assert result.ambiguity is True
    assert result.run_confirmed is False
    assert (
        result.for_hypothesis("hyp_001").status
        is HypothesisStatus.SUPPORTED
    )
    assert (
        result.for_hypothesis("hyp_002").status
        is HypothesisStatus.SUPPORTED
    )
