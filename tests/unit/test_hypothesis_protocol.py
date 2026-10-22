"""Unit tests for hypothesis proposal and evidence assessment validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tracemind.diagnosis.evidence import (
    AssessmentVerdict,
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
)
from tracemind.diagnosis.ledger import EvidenceLedger
from tracemind.diagnosis.workspace import (
    AssessmentProposal,
    AssessmentsProposal,
    DiagnosisWorkspace,
    HypothesisProposal,
    ProtocolError,
    RequirementProposal,
)


def _evidence(
    evidence_id: str,
    kind: EvidenceKind,
    source_ref: str,
    *,
    tool_call_id: str | None = None,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        claim=f"{kind.value} claim",
        source_ref=source_ref,
        provenance=(
            EvidenceProvenance.TOOL
            if tool_call_id is not None
            else EvidenceProvenance.LOG_PARSER
        ),
        tool_call_id=tool_call_id,
        observed_at="2026-10-22T00:00:00+00:00",
    )


def _workspace() -> DiagnosisWorkspace:
    ledger = EvidenceLedger()
    ledger.add(_evidence("ev_0001", EvidenceKind.LOG_EVENT, "log://evt_0001"))
    ledger.add(
        _evidence(
            "ev_0002",
            EvidenceKind.SOURCE_CODE,
            "repo://OrderService.java#L17-L27",
        )
    )
    ledger.add(
        _evidence(
            "ev_0003",
            EvidenceKind.STACK_FRAME,
            "log://evt_0003",
        )
    )
    ledger.add(
        _evidence(
            "ev_0004",
            EvidenceKind.LOG_EVENT,
            "log://evt_0003",
        )
    )
    return DiagnosisWorkspace(ledger)


def _requirement(
    *,
    kinds: list[EvidenceKind] | None = None,
    discriminating: bool = True,
) -> RequirementProposal:
    return RequirementProposal(
        description="observable verification condition",
        evidence_kinds=(
            kinds if kinds is not None else [EvidenceKind.LOG_EVENT]
        ),
        discriminating=discriminating,
        suggested_tools=["logs.search"],
    )


def _proposal(
    *,
    basis_ids: list[str] | None = None,
    basis_refs: list[str] | None = None,
    requirements: list[RequirementProposal] | None = None,
) -> HypothesisProposal:
    return HypothesisProposal(
        statement="orders row is missing, so the update affected zero rows",
        cause_chain=["callback arrives", "update affects zero rows"],
        basis_evidence_ids=basis_ids if basis_ids is not None else ["ev_0001"],
        basis_source_refs=basis_refs or [],
        requirements=requirements
        if requirements is not None
        else [
            _requirement(),
            _requirement(
                kinds=[EvidenceKind.SOURCE_CODE],
                discriminating=False,
            ),
        ],
        falsifiers=["the row exists with the expected status"],
    )


def _assessment(
    *,
    evidence_id: str | None,
    source_ref: str | None = None,
    verdict: AssessmentVerdict = AssessmentVerdict.SUPPORTS,
    rationale: str = "the observed evidence matches the requirement",
) -> AssessmentProposal:
    return AssessmentProposal(
        hypothesis_id="hyp_001",
        requirement_id="hyp_001_req_01",
        evidence_id=evidence_id,
        source_ref=source_ref,
        verdict=verdict,
        rationale=rationale,
    )


def test_valid_proposal_assigns_runtime_ids() -> None:
    workspace = _workspace()

    result = workspace.propose_hypothesis(_proposal())

    assert result["hypothesis_id"] == "hyp_001"
    assert result["requirement_ids"] == ["hyp_001_req_01", "hyp_001_req_02"]
    assert result["status"] == "candidate"
    hypothesis = workspace.get_hypothesis("hyp_001")
    assert hypothesis is not None
    assert hypothesis.basis_evidence_ids == ["ev_0001"]
    assert hypothesis.source == "llm"


def test_source_ref_basis_matches_multiple_evidence_and_deduplicates() -> None:
    workspace = _workspace()

    result = workspace.propose_hypothesis(
        _proposal(basis_ids=[], basis_refs=["log://evt_0003"])
    )

    hypothesis = workspace.get_hypothesis(str(result["hypothesis_id"]))
    assert hypothesis is not None
    assert hypothesis.basis_evidence_ids == ["ev_0003", "ev_0004"]


def test_missing_basis_is_rejected() -> None:
    workspace = _workspace()

    with pytest.raises(ProtocolError) as exc:
        workspace.propose_hypothesis(_proposal(basis_ids=[]))

    assert exc.value.code == "HYPOTHESIS_NOT_GROUNDED"


def test_nonexistent_basis_evidence_is_rejected() -> None:
    workspace = _workspace()

    with pytest.raises(ProtocolError) as exc:
        workspace.propose_hypothesis(_proposal(basis_ids=["ev_9999"]))

    assert exc.value.code == "HYPOTHESIS_NOT_GROUNDED"
    assert "ev_9999" in exc.value.message


def test_unresolvable_basis_source_ref_is_rejected() -> None:
    workspace = _workspace()

    with pytest.raises(ProtocolError) as exc:
        workspace.propose_hypothesis(
            _proposal(basis_ids=[], basis_refs=["repo://missing.java#L1-L2"])
        )

    assert exc.value.code == "HYPOTHESIS_NOT_GROUNDED"


def test_requirements_must_include_a_discriminating_requirement() -> None:
    workspace = _workspace()

    with pytest.raises(ProtocolError) as exc:
        workspace.propose_hypothesis(
            _proposal(
                requirements=[
                    _requirement(discriminating=False),
                ]
            )
        )

    assert exc.value.code == "HYPOTHESIS_NOT_GROUNDED"


def test_requirements_must_not_be_empty() -> None:
    workspace = _workspace()

    with pytest.raises(ProtocolError) as exc:
        workspace.propose_hypothesis(_proposal(requirements=[]))

    assert exc.value.code == "HYPOTHESIS_NOT_GROUNDED"


def test_requirement_must_declare_evidence_kinds() -> None:
    workspace = _workspace()

    with pytest.raises(ProtocolError) as exc:
        workspace.propose_hypothesis(
            _proposal(requirements=[_requirement(kinds=[])])
        )

    assert exc.value.code == "HYPOTHESIS_NOT_GROUNDED"


def test_hypothesis_limit_is_enforced() -> None:
    workspace = DiagnosisWorkspace(
        _workspace().ledger,
        max_hypotheses=1,
    )
    workspace.propose_hypothesis(_proposal())

    with pytest.raises(ProtocolError) as exc:
        workspace.propose_hypothesis(_proposal())

    assert exc.value.code == "HYPOTHESIS_NOT_GROUNDED"


def test_requirement_limit_is_enforced() -> None:
    workspace = DiagnosisWorkspace(
        _workspace().ledger,
        max_requirements_per_hypothesis=1,
    )

    with pytest.raises(ProtocolError) as exc:
        workspace.propose_hypothesis(_proposal())

    assert exc.value.code == "HYPOTHESIS_NOT_GROUNDED"


def test_extra_runtime_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        HypothesisProposal(
            statement="grounded",
            cause_chain=["one"],
            basis_evidence_ids=["ev_0001"],
            requirements=[_requirement()],
            falsifiers=["none"],
            hypothesis_id="hyp_999",
        )


def test_assessment_by_evidence_id_supports() -> None:
    workspace = _workspace()
    workspace.propose_hypothesis(_proposal())
    workspace.ledger.add(
        _evidence("ev_0010", EvidenceKind.LOG_EVENT, "log://evt_0010")
    )
    workspace.ledger.bind(
        "ev_0010",
        "hyp_001",
        "hyp_001_req_01",
        tool_call_id="call_1",
    )

    result = workspace.assess_evidence(
        AssessmentsProposal(assessments=[_assessment(evidence_id="ev_0010")])
    )

    assert result["assessment_ids"] == ["asm_0001"]
    assert workspace.assessments[0].verdict is AssessmentVerdict.SUPPORTS


def test_assessment_by_unique_source_ref_supports() -> None:
    workspace = _workspace()
    workspace.propose_hypothesis(_proposal())
    workspace.ledger.add(
        _evidence("ev_0010", EvidenceKind.LOG_EVENT, "log://evt_0010")
    )
    workspace.ledger.bind("ev_0010", "hyp_001", "hyp_001_req_01")

    result = workspace.assess_evidence(
        AssessmentsProposal(
            assessments=[_assessment(evidence_id=None, source_ref="log://evt_0010")]
        )
    )

    assert result["assessment_ids"] == ["asm_0001"]


def test_assessment_rejects_ambiguous_source_ref() -> None:
    workspace = _workspace()
    workspace.propose_hypothesis(
        _proposal(
            requirements=[
                _requirement(
                    kinds=[EvidenceKind.STACK_FRAME, EvidenceKind.LOG_EVENT]
                )
            ]
        )
    )
    workspace.ledger.bind("ev_0003", "hyp_001", "hyp_001_req_01")
    workspace.ledger.bind("ev_0004", "hyp_001", "hyp_001_req_01")

    with pytest.raises(ProtocolError) as exc:
        workspace.assess_evidence(
            AssessmentsProposal(
                assessments=[
                    _assessment(evidence_id=None, source_ref="log://evt_0003")
                ]
            )
        )

    assert exc.value.code == "INVALID_ASSESSMENT"
    assert "exactly one" in exc.value.message


def test_same_evidence_can_be_assessed_for_two_hypotheses() -> None:
    workspace = _workspace()
    workspace.propose_hypothesis(_proposal())
    workspace.propose_hypothesis(_proposal())
    workspace.ledger.add(
        _evidence("ev_0010", EvidenceKind.LOG_EVENT, "log://evt_0010")
    )
    workspace.ledger.bind("ev_0010", "hyp_001", "hyp_001_req_01")
    workspace.ledger.bind("ev_0010", "hyp_002", "hyp_002_req_01")

    result = workspace.assess_evidence(
        AssessmentsProposal(
            assessments=[
                _assessment(evidence_id="ev_0010"),
                AssessmentProposal(
                    hypothesis_id="hyp_002",
                    requirement_id="hyp_002_req_01",
                    evidence_id="ev_0010",
                    verdict=AssessmentVerdict.REFUTES,
                    rationale="the alternative hypothesis predicts the opposite",
                ),
            ]
        )
    )

    assert result["assessment_ids"] == ["asm_0001", "asm_0002"]
    assert workspace.assessments[0].verdict is AssessmentVerdict.SUPPORTS
    assert workspace.assessments[1].verdict is AssessmentVerdict.REFUTES


def test_assessment_reuses_unbound_tool_evidence() -> None:
    workspace = _workspace()
    workspace.propose_hypothesis(_proposal())
    workspace.ledger.add(
        _evidence(
            "ev_0010",
            EvidenceKind.LOG_EVENT,
            "log://evt_0010",
            tool_call_id="call_1",
        )
    )
    assert not workspace.ledger.get("ev_0010").has_binding(
        "hyp_001",
        "hyp_001_req_01",
    )

    result = workspace.assess_evidence(
        AssessmentsProposal(
            assessments=[_assessment(evidence_id="ev_0010")]
        )
    )

    assert result["assessment_ids"] == ["asm_0001"]
    evidence = workspace.ledger.get("ev_0010")
    assert evidence is not None
    assert evidence.has_binding("hyp_001", "hyp_001_req_01")
    assert workspace.ledger.by_requirement(
        "hyp_001",
        "hyp_001_req_01",
    ) == [evidence]


def test_assessment_reuses_tool_evidence_by_source_ref() -> None:
    workspace = _workspace()
    workspace.propose_hypothesis(_proposal())
    workspace.ledger.add(
        _evidence(
            "ev_0010",
            EvidenceKind.LOG_EVENT,
            "log://evt_0010",
            tool_call_id="call_1",
        )
    )

    result = workspace.assess_evidence(
        AssessmentsProposal(
            assessments=[
                _assessment(
                    evidence_id=None,
                    source_ref="log://evt_0010",
                )
            ]
        )
    )

    assert result["assessment_ids"] == ["asm_0001"]


def test_assessment_rejects_unbound_evidence() -> None:
    workspace = _workspace()
    workspace.propose_hypothesis(_proposal())
    workspace.ledger.add(
        _evidence("ev_0010", EvidenceKind.LOG_EVENT, "log://evt_0010")
    )

    with pytest.raises(ProtocolError) as exc:
        workspace.assess_evidence(
            AssessmentsProposal(
                assessments=[_assessment(evidence_id="ev_0010")]
            )
        )

    assert exc.value.code == "INVALID_ASSESSMENT"


def test_assessment_rejects_kind_mismatch() -> None:
    workspace = _workspace()
    workspace.propose_hypothesis(_proposal())
    workspace.ledger.add(
        _evidence(
            "ev_0010",
            EvidenceKind.SOURCE_CODE,
            "repo://OrderService.java#L1-L2",
        )
    )
    workspace.ledger.bind("ev_0010", "hyp_001", "hyp_001_req_01")

    with pytest.raises(ProtocolError) as exc:
        workspace.assess_evidence(
            AssessmentsProposal(
                assessments=[_assessment(evidence_id="ev_0010")]
            )
        )

    assert exc.value.code == "INVALID_ASSESSMENT"


def test_assessment_rejects_unknown_hypothesis_or_requirement() -> None:
    workspace = _workspace()
    workspace.propose_hypothesis(_proposal())

    with pytest.raises(ProtocolError) as exc:
        workspace.assess_evidence(
            AssessmentsProposal(
                assessments=[
                    AssessmentProposal(
                        hypothesis_id="hyp_999",
                        requirement_id="hyp_001_req_01",
                        evidence_id="ev_0001",
                        verdict=AssessmentVerdict.SUPPORTS,
                        rationale="bad target",
                    )
                ]
            )
        )
    assert exc.value.code == "INVALID_ASSESSMENT"

    with pytest.raises(ProtocolError) as exc:
        workspace.assess_evidence(
            AssessmentsProposal(
                assessments=[
                    AssessmentProposal(
                        hypothesis_id="hyp_001",
                        requirement_id="hyp_001_req_99",
                        evidence_id="ev_0001",
                        verdict=AssessmentVerdict.SUPPORTS,
                        rationale="bad target",
                    )
                ]
            )
        )
    assert exc.value.code == "INVALID_ASSESSMENT"


def test_assessment_rejects_both_and_neither_selectors() -> None:
    workspace = _workspace()
    workspace.propose_hypothesis(_proposal())

    with pytest.raises(ProtocolError) as exc:
        workspace.assess_evidence(
            AssessmentsProposal(
                assessments=[
                    _assessment(
                        evidence_id="ev_0001",
                        source_ref="log://evt_0001",
                    )
                ]
            )
        )
    assert exc.value.code == "INVALID_ASSESSMENT"

    with pytest.raises(ProtocolError) as exc:
        workspace.assess_evidence(
            AssessmentsProposal(
                assessments=[_assessment(evidence_id=None)]
            )
        )
    assert exc.value.code == "INVALID_ASSESSMENT"


def test_reassessment_revises_existing_verdict() -> None:
    workspace = _workspace()
    workspace.propose_hypothesis(_proposal())
    workspace.ledger.add(
        _evidence("ev_0010", EvidenceKind.LOG_EVENT, "log://evt_0010")
    )
    workspace.ledger.bind("ev_0010", "hyp_001", "hyp_001_req_01")
    first = workspace.assess_evidence(
        AssessmentsProposal(
            assessments=[
                _assessment(
                    evidence_id=None,
                    source_ref="log://evt_0010",
                    verdict=AssessmentVerdict.NEUTRAL,
                )
            ]
        )
    )

    second = workspace.assess_evidence(
        AssessmentsProposal(
            assessments=[
                _assessment(
                    evidence_id="ev_0010",
                    verdict=AssessmentVerdict.SUPPORTS,
                )
            ]
        )
    )

    assert first["assessment_ids"] == ["asm_0001"]
    assert second["assessment_ids"] == ["asm_0001"]
    assert second["revised_assessment_ids"] == ["asm_0001"]
    assert second["rejected"] == []
    assert len(workspace.assessments) == 1
    assert workspace.assessments[0].verdict is AssessmentVerdict.SUPPORTS
    assert workspace.assessments[0].revised_at is not None


def test_duplicate_assessment_within_batch_keeps_first_item() -> None:
    workspace = _workspace()
    workspace.propose_hypothesis(_proposal())
    workspace.ledger.add(
        _evidence("ev_0010", EvidenceKind.LOG_EVENT, "log://evt_0010")
    )
    workspace.ledger.bind("ev_0010", "hyp_001", "hyp_001_req_01")

    result = workspace.assess_evidence(
        AssessmentsProposal(
            assessments=[
                _assessment(evidence_id="ev_0010"),
                _assessment(evidence_id="ev_0010"),
            ]
        )
    )

    assert result["assessment_ids"] == ["asm_0001"]
    rejected = result["rejected"]
    assert isinstance(rejected, list) and len(rejected) == 1
    assert "duplicate assessment within this batch" in str(
        rejected[0]["reason"]
    )
    assert len(workspace.assessments) == 1


def test_partial_batch_keeps_valid_assessments() -> None:
    workspace = _workspace()
    workspace.propose_hypothesis(_proposal())
    workspace.ledger.add(
        _evidence("ev_0010", EvidenceKind.LOG_EVENT, "log://evt_0010")
    )
    workspace.ledger.bind("ev_0010", "hyp_001", "hyp_001_req_01")

    result = workspace.assess_evidence(
        AssessmentsProposal(
            assessments=[
                _assessment(evidence_id="ev_0010"),
                _assessment(evidence_id="ev_missing"),
            ]
        )
    )

    assert result["assessment_ids"] == ["asm_0001"]
    rejected = result["rejected"]
    assert isinstance(rejected, list) and len(rejected) == 1
    assert rejected[0]["index"] == 2
    assert "evidence does not exist" in str(rejected[0]["reason"])


def test_empty_rationale_is_rejected() -> None:
    workspace = _workspace()
    workspace.propose_hypothesis(_proposal())
    workspace.ledger.add(
        _evidence("ev_0010", EvidenceKind.LOG_EVENT, "log://evt_0010")
    )
    workspace.ledger.bind("ev_0010", "hyp_001", "hyp_001_req_01")

    with pytest.raises(ProtocolError) as exc:
        workspace.assess_evidence(
            AssessmentsProposal(
                assessments=[
                    _assessment(evidence_id="ev_0010", rationale="   ")
                ]
            )
        )

    assert exc.value.code == "INVALID_ASSESSMENT"
