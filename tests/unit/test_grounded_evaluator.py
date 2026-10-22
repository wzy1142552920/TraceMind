"""Unit tests for deterministic grounded hypothesis evaluation."""

from __future__ import annotations

from tracemind.diagnosis.evaluator import evaluate_hypotheses
from tracemind.diagnosis.evidence import (
    AssessmentVerdict,
    Evidence,
    EvidenceAssessment,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceRequirement,
    Hypothesis,
    HypothesisStatus,
)

THREAD = "http-nio-8080-exec-7"
THREAD_REF = f"log://incident.log#thread={THREAD}&L2-L5"


def _requirement(
    requirement_id: str,
    kind: EvidenceKind,
    *,
    discriminating: bool,
) -> EvidenceRequirement:
    return EvidenceRequirement(
        requirement_id=requirement_id,
        description=f"evidence of kind {kind.value}",
        evidence_kinds=[kind],
        discriminating=discriminating,
    )


def _hypothesis(
    hypothesis_id: str = "hyp_001",
    *,
    with_thread: bool = True,
) -> Hypothesis:
    requirements = [
        _requirement("hyp_001_req_code", EvidenceKind.SOURCE_CODE, discriminating=False),
        _requirement("hyp_001_req_db", EvidenceKind.DB_ROW, discriminating=True),
    ]
    if with_thread:
        requirements.insert(
            0,
            _requirement(
                "hyp_001_req_ctx",
                EvidenceKind.LOG_THREAD_CONTEXT,
                discriminating=True,
            ),
        )
    return Hypothesis(
        hypothesis_id=hypothesis_id,
        statement="orders row is missing",
        cause_chain=["callback", "zero rows"],
        basis_evidence_ids=["ev_0001"],
        requirements=requirements,
        falsifiers=["row exists"],
    )


def _distractor() -> Hypothesis:
    return Hypothesis(
        hypothesis_id="hyp_002",
        statement="the mapper SQL is wrong",
        cause_chain=["callback", "wrong update predicate"],
        basis_evidence_ids=["ev_0001"],
        requirements=[
            _requirement(
                "hyp_002_req_db",
                EvidenceKind.DB_ROW,
                discriminating=True,
            )
        ],
        falsifiers=["row exists and SQL matches"],
    )


def _evidence(
    evidence_id: str,
    kind: EvidenceKind,
    source_ref: str,
    *,
    bound_hypothesis: str,
    bound_requirement: str,
    tool_call_id: str = "call_1",
    thread: str | None = None,
) -> Evidence:
    content = {"thread": thread} if thread is not None else {}
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        claim=f"{kind.value} claim",
        source_ref=source_ref,
        provenance=EvidenceProvenance.TOOL,
        tool_call_id=tool_call_id,
        observed_at="2026-10-22T00:00:00+00:00",
        bound_hypothesis_id=bound_hypothesis,
        bound_requirement_id=bound_requirement,
        content=content,
    )


def _assessment(
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
        created_at="2026-10-22T00:00:00+00:00",
    )


def _supported_scenario() -> tuple[
    list[Hypothesis],
    list[Evidence],
    list[EvidenceAssessment],
]:
    hypotheses = [_hypothesis(), _distractor()]
    evidence = [
        Evidence(
            evidence_id="ev_0001",
            kind=EvidenceKind.LOG_EVENT,
            claim="primary event",
            source_ref="log://evt_0003",
            provenance=EvidenceProvenance.LOG_PARSER,
            observed_at="2026-10-22T00:00:00+00:00",
        ),
        _evidence(
            "ev_ctx",
            EvidenceKind.LOG_THREAD_CONTEXT,
            THREAD_REF,
            bound_hypothesis="hyp_001",
            bound_requirement="hyp_001_req_ctx",
            thread=THREAD,
        ),
        _evidence(
            "ev_code",
            EvidenceKind.SOURCE_CODE,
            "repo://src/OrderService.java#L17-L27",
            bound_hypothesis="hyp_001",
            bound_requirement="hyp_001_req_code",
        ),
        _evidence(
            "ev_db",
            EvidenceKind.DB_ROW,
            "db://orders/id=10086",
            bound_hypothesis="hyp_001",
            bound_requirement="hyp_001_req_db",
        ),
        _evidence(
            "ev_alt",
            EvidenceKind.DB_ROW,
            "db://orders/id=10086?view=alt",
            bound_hypothesis="hyp_002",
            bound_requirement="hyp_002_req_db",
        ),
    ]
    assessments = [
        _assessment("asm_1", "hyp_001", "hyp_001_req_ctx", "ev_ctx"),
        _assessment("asm_2", "hyp_001", "hyp_001_req_code", "ev_code"),
        _assessment("asm_3", "hyp_001", "hyp_001_req_db", "ev_db"),
        _assessment(
            "asm_4",
            "hyp_002",
            "hyp_002_req_db",
            "ev_alt",
            AssessmentVerdict.REFUTES,
        ),
    ]
    return hypotheses, evidence, assessments


def test_single_qualifying_hypothesis_with_alternatives_excluded_confirms() -> None:
    hypotheses, evidence, assessments = _supported_scenario()

    result = evaluate_hypotheses(
        hypotheses,
        evidence,
        assessments,
        require_log_thread_context=True,
        required_log_thread=THREAD,
    )

    first = result.for_hypothesis("hyp_001")
    second = result.for_hypothesis("hyp_002")
    assert first is not None and second is not None
    assert first.status is HypothesisStatus.CONFIRMED
    assert first.qualifies is True
    assert first.missing_requirement_ids == []
    assert second.status is HypothesisStatus.CONTRADICTED
    assert result.run_confirmed is True
    assert result.ambiguity is False
    assert result.top_hypothesis_id == "hyp_001"
    assert first.ranking_score == 13


def test_same_fact_can_support_one_hypothesis_and_refute_another() -> None:
    hypotheses, evidence, assessments = _supported_scenario()
    shared = next(item for item in evidence if item.evidence_id == "ev_db")
    shared.add_binding("hyp_002", "hyp_002_req_db", "call_2")
    assessments = [
        item
        for item in assessments
        if item.evidence_id != "ev_alt"
    ]
    assessments.append(
        _assessment(
            "asm_4",
            "hyp_002",
            "hyp_002_req_db",
            "ev_db",
            AssessmentVerdict.REFUTES,
        )
    )

    result = evaluate_hypotheses(
        hypotheses,
        evidence,
        assessments,
        require_log_thread_context=True,
        required_log_thread=THREAD,
    )

    first = result.for_hypothesis("hyp_001")
    second = result.for_hypothesis("hyp_002")
    assert first is not None and second is not None
    assert shared.has_binding("hyp_001", "hyp_001_req_db")
    assert shared.has_binding("hyp_002", "hyp_002_req_db")
    assert first.status is HypothesisStatus.CONFIRMED
    assert second.status is HypothesisStatus.CONTRADICTED
    assert result.run_confirmed is True


def test_single_hypothesis_cannot_be_confirmed() -> None:
    hypotheses, evidence, assessments = _supported_scenario()
    hypotheses = [hypotheses[0]]
    assessments = [
        item for item in assessments if item.hypothesis_id == "hyp_001"
    ]

    result = evaluate_hypotheses(
        hypotheses,
        evidence,
        assessments,
        require_log_thread_context=True,
        required_log_thread=THREAD,
    )

    first = result.for_hypothesis("hyp_001")
    assert first is not None
    assert first.qualifies is True
    assert first.status is HypothesisStatus.SUPPORTED
    assert result.run_confirmed is False


def test_open_alternative_prevents_confirmation() -> None:
    hypotheses, evidence, assessments = _supported_scenario()
    assessments = [item for item in assessments if item.hypothesis_id == "hyp_001"]

    result = evaluate_hypotheses(
        hypotheses,
        evidence,
        assessments,
        require_log_thread_context=True,
        required_log_thread=THREAD,
    )

    first = result.for_hypothesis("hyp_001")
    second = result.for_hypothesis("hyp_002")
    assert first is not None and second is not None
    assert first.qualifies is True
    assert first.status is HypothesisStatus.SUPPORTED
    assert second.status is HypothesisStatus.CANDIDATE
    assert result.run_confirmed is False


def test_two_qualifying_hypotheses_are_ambiguous() -> None:
    hypotheses, evidence, assessments = _supported_scenario()
    evidence.append(
        _evidence(
            "ev_ctx_alt",
            EvidenceKind.LOG_THREAD_CONTEXT,
            f"log://incident.log#thread={THREAD}&L1-L5",
            bound_hypothesis="hyp_002",
            bound_requirement="hyp_002_req_db",
            thread=THREAD,
        )
    )
    evidence.append(
        _evidence(
            "ev_code_alt",
            EvidenceKind.SOURCE_CODE,
            "repo://src/OrderMapper.java#L14-L18",
            bound_hypothesis="hyp_002",
            bound_requirement="hyp_002_req_db",
        )
    )
    hypotheses[1] = Hypothesis(
        hypothesis_id="hyp_002",
        statement="SQL predicate is wrong",
        cause_chain=["callback", "wrong SQL"],
        basis_evidence_ids=["ev_0001"],
        requirements=[
            _requirement(
                "hyp_002_req_db",
                EvidenceKind.LOG_THREAD_CONTEXT,
                discriminating=True,
            ),
            _requirement(
                "hyp_002_req_code",
                EvidenceKind.SOURCE_CODE,
                discriminating=False,
            ),
        ],
        falsifiers=["SQL matches"],
    )
    evidence[-2].bound_requirement_id = "hyp_002_req_db"
    evidence[-1].bound_requirement_id = "hyp_002_req_code"
    assessments = [
        item for item in assessments if item.assessment_id != "asm_4"
    ]
    assessments.append(
        _assessment(
            "asm_5",
            "hyp_002",
            "hyp_002_req_db",
            "ev_ctx_alt",
        )
    )
    assessments.append(
        _assessment(
            "asm_6",
            "hyp_002",
            "hyp_002_req_code",
            "ev_code_alt",
        )
    )

    result = evaluate_hypotheses(
        hypotheses,
        evidence,
        assessments,
        require_log_thread_context=True,
        required_log_thread=THREAD,
    )

    assert result.ambiguity is True
    assert result.run_confirmed is False
    assert result.for_hypothesis("hyp_001").status is HypothesisStatus.SUPPORTED
    assert result.for_hypothesis("hyp_002").status is HypothesisStatus.SUPPORTED


def test_context_gate_requires_same_thread_when_enabled() -> None:
    hypotheses, evidence, assessments = _supported_scenario()
    assessments = [
        item
        for item in assessments
        if item.evidence_id != "ev_ctx"
    ]

    result = evaluate_hypotheses(
        hypotheses,
        evidence,
        assessments,
        require_log_thread_context=True,
        required_log_thread=THREAD,
    )

    first = result.for_hypothesis("hyp_001")
    assert first is not None
    assert first.qualifies is False
    assert first.status is HypothesisStatus.SUPPORTED
    assert any("same-thread" in reason for reason in first.reasons)
    assert result.run_confirmed is False


def test_cross_thread_context_cannot_satisfy_gate() -> None:
    hypotheses, evidence, assessments = _supported_scenario()
    evidence[1] = _evidence(
        "ev_ctx",
        EvidenceKind.LOG_THREAD_CONTEXT,
        "log://incident.log#thread=other-thread&L2-L5",
        bound_hypothesis="hyp_001",
        bound_requirement="hyp_001_req_ctx",
        thread="other-thread",
    )

    result = evaluate_hypotheses(
        hypotheses,
        evidence,
        assessments,
        require_log_thread_context=True,
        required_log_thread=THREAD,
    )

    assert result.for_hypothesis("hyp_001").qualifies is False
    assert result.run_confirmed is False


def test_content_and_source_ref_thread_mismatch_is_rejected() -> None:
    hypotheses, evidence, assessments = _supported_scenario()
    evidence[1] = _evidence(
        "ev_ctx",
        EvidenceKind.LOG_THREAD_CONTEXT,
        THREAD_REF,
        bound_hypothesis="hyp_001",
        bound_requirement="hyp_001_req_ctx",
        thread="different-thread",
    )

    result = evaluate_hypotheses(
        hypotheses,
        evidence,
        assessments,
        require_log_thread_context=True,
        required_log_thread=THREAD,
    )

    assert result.for_hypothesis("hyp_001").qualifies is False
    assert result.run_confirmed is False


def test_context_gate_disabled_does_not_require_thread_evidence() -> None:
    hypotheses = [_hypothesis(with_thread=False), _distractor()]
    hypotheses[0].requirements.append(
        _requirement(
            "hyp_001_req_log",
            EvidenceKind.LOG_EVENT,
            discriminating=False,
        )
    )
    evidence = [
        Evidence(
            evidence_id="ev_0001",
            kind=EvidenceKind.LOG_EVENT,
            claim="primary event",
            source_ref="log://evt_0003",
            provenance=EvidenceProvenance.LOG_PARSER,
            observed_at="2026-10-22T00:00:00+00:00",
        ),
        _evidence(
            "ev_log",
            EvidenceKind.LOG_EVENT,
            "log://evt_0002",
            bound_hypothesis="hyp_001",
            bound_requirement="hyp_001_req_log",
        ),
        _evidence(
            "ev_code",
            EvidenceKind.SOURCE_CODE,
            "repo://src/OrderService.java#L17-L27",
            bound_hypothesis="hyp_001",
            bound_requirement="hyp_001_req_code",
        ),
        _evidence(
            "ev_db",
            EvidenceKind.DB_ROW,
            "db://orders/id=10086",
            bound_hypothesis="hyp_001",
            bound_requirement="hyp_001_req_db",
        ),
        _evidence(
            "ev_alt",
            EvidenceKind.DB_ROW,
            "db://orders/id=10086?view=alt",
            bound_hypothesis="hyp_002",
            bound_requirement="hyp_002_req_db",
        ),
    ]
    assessments = [
        _assessment("asm_0", "hyp_001", "hyp_001_req_log", "ev_log"),
        _assessment("asm_1", "hyp_001", "hyp_001_req_code", "ev_code"),
        _assessment("asm_2", "hyp_001", "hyp_001_req_db", "ev_db"),
        _assessment(
            "asm_3",
            "hyp_002",
            "hyp_002_req_db",
            "ev_alt",
            AssessmentVerdict.REFUTES,
        ),
    ]

    result = evaluate_hypotheses(
        hypotheses,
        evidence,
        assessments,
        require_log_thread_context=False,
    )

    assert result.for_hypothesis("hyp_001").status is HypothesisStatus.CONFIRMED
    assert result.run_confirmed is True


def test_refute_is_terminal_and_supports_do_not_override_it() -> None:
    hypotheses, evidence, assessments = _supported_scenario()
    evidence.append(
        _evidence(
            "ev_db_second",
            EvidenceKind.DB_ROW,
            "db://orders/id=10086?second=true",
            bound_hypothesis="hyp_001",
            bound_requirement="hyp_001_req_db",
            tool_call_id="call_2",
        )
    )
    assessments.append(
        _assessment(
            "asm_refute",
            "hyp_001",
            "hyp_001_req_db",
            "ev_db_second",
            AssessmentVerdict.REFUTES,
        )
    )

    result = evaluate_hypotheses(
        hypotheses,
        evidence,
        assessments,
        require_log_thread_context=True,
        required_log_thread=THREAD,
    )

    first = result.for_hypothesis("hyp_001")
    assert first is not None
    assert first.status is HypothesisStatus.CONTRADICTED
    assert first.refuting_evidence_ids == ["ev_db_second"]
    assert result.run_confirmed is False
    assert result.top_hypothesis_id != "hyp_001"


def test_unbound_or_kind_mismatched_assessment_does_not_satisfy_requirement() -> None:
    hypotheses, evidence, assessments = _supported_scenario()
    evidence.append(
        _evidence(
            "ev_wrong_kind",
            EvidenceKind.SQL,
            "repo://src/OrderMapper.java#L16-L16",
            bound_hypothesis="hyp_001",
            bound_requirement="hyp_001_req_code",
        )
    )
    evidence.append(
        Evidence(
            evidence_id="ev_unbound",
            kind=EvidenceKind.SOURCE_CODE,
            claim="unbound source",
            source_ref="repo://src/Other.java#L1-L2",
            provenance=EvidenceProvenance.AST_INDEX,
            observed_at="2026-10-22T00:00:00+00:00",
        )
    )
    assessments = [
        item
        for item in assessments
        if item.evidence_id != "ev_code"
    ]
    assessments.append(
        _assessment(
            "asm_bad_kind",
            "hyp_001",
            "hyp_001_req_code",
            "ev_wrong_kind",
        )
    )
    assessments.append(
        _assessment(
            "asm_unbound",
            "hyp_001",
            "hyp_001_req_code",
            "ev_unbound",
        )
    )

    result = evaluate_hypotheses(
        hypotheses,
        evidence,
        assessments,
        require_log_thread_context=True,
        required_log_thread=THREAD,
    )

    first = result.for_hypothesis("hyp_001")
    assert first is not None
    assert "hyp_001_req_code" in first.missing_requirement_ids
    assert first.status is HypothesisStatus.SUPPORTED


def test_candidate_without_assessment_is_candidate() -> None:
    result = evaluate_hypotheses(
        [_hypothesis()],
        [
            Evidence(
                evidence_id="ev_0001",
                kind=EvidenceKind.LOG_EVENT,
                claim="primary event",
                source_ref="log://evt_0003",
                provenance=EvidenceProvenance.LOG_PARSER,
                observed_at="2026-10-22T00:00:00+00:00",
            )
        ],
        [],
    )

    first = result.for_hypothesis("hyp_001")
    assert first is not None
    assert first.status is HypothesisStatus.CANDIDATE
    assert first.qualifies is False
    assert result.run_confirmed is False
