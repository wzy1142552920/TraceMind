"""Unit tests for deterministic remediation validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracemind.diagnosis.evidence import (
    AssessmentVerdict,
    Evidence,
    EvidenceAssessment,
    EvidenceKind,
    EvidenceRequirement,
    Hypothesis,
    HypothesisStatus,
)
from tracemind.diagnosis.ledger import EvidenceLedger
from tracemind.diagnosis.remediation import (
    RemediationActionProposal,
    RemediationProposal,
)
from tracemind.diagnosis.workspace import DiagnosisWorkspace, ProtocolError
from tracemind.verification import load_verification_data

REPO_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "repos"
    / "minimal-order-service"
)
CREATED_AT = "2026-10-21T00:00:00+00:00"
CODE_TARGET = "src/main/java/com/example/order/OrderService.java"
VALID_DATA = {
    "backend": "fake",
    "tables": {
        "orders": {
            "primary_key": "id",
            "columns": ["id", "status"],
            "rows": [{"id": 10086, "status": "PAID"}],
        }
    },
}


def _evidence(
    evidence_id: str,
    source_ref: str,
    *,
    kind: EvidenceKind = EvidenceKind.LOG_EVENT,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        claim=f"Evidence {evidence_id}",
        source_ref=source_ref,
        strength="strong",
        provenance="log_parser",
        observed_at=CREATED_AT,
    )


def _workspace(
    *,
    status: HypothesisStatus = HypothesisStatus.SUPPORTED,
    max_remediation_actions: int = 8,
    max_actions_per_hypothesis: int = 3,
) -> DiagnosisWorkspace:
    ledger = EvidenceLedger()
    ledger.add(_evidence("ev_0001", "log://evt_0001"))
    ledger.add(_evidence("ev_0002", "log://evt_0002"))
    ledger.add(
        _evidence(
            "ev_0003",
            "db://orders/id=10086",
            kind=EvidenceKind.DB_ROW,
        )
    )
    workspace = DiagnosisWorkspace(
        ledger,
        max_remediation_actions=max_remediation_actions,
        max_actions_per_hypothesis=max_actions_per_hypothesis,
    )
    workspace.hypotheses.append(
        Hypothesis(
            hypothesis_id="hyp_001",
            statement="The order row is missing",
            status=status,
            basis_evidence_ids=["ev_0001"],
            evidence_ids=["ev_0001", "ev_0003"],
            requirements=[
                EvidenceRequirement(
                    requirement_id="hyp_001_req_01",
                    description="The order row is absent",
                    evidence_kinds=[EvidenceKind.LOG_EVENT],
                    discriminating=True,
                )
            ],
        )
    )
    return workspace


def _backend(tmp_path: Path):
    path = tmp_path / "verification.json"
    path.write_text(json.dumps(VALID_DATA), encoding="utf-8")
    return load_verification_data(path)


def _action(**overrides: object) -> RemediationActionProposal:
    data: dict[str, object] = {
        "hypothesis_id": "hyp_001",
        "type": "code",
        "title": "Handle the missing order row",
        "description": "Return an explicit business error when the row is absent.",
        "evidence_ids": ["ev_0001"],
        "target": CODE_TARGET,
        "risk": "Changes caller-visible failure semantics.",
        "prerequisites": ["Confirm the callback contract."],
        "verification_steps": ["Add a duplicate-callback test."],
    }
    data.update(overrides)
    return RemediationActionProposal.model_validate(data)


def _propose(
    workspace: DiagnosisWorkspace,
    actions: list[RemediationActionProposal],
    *,
    backend=None,
) -> dict[str, object]:
    return workspace.propose_remediation(
        RemediationProposal(actions=actions),
        repo_root=REPO_FIXTURE,
        verification_backend=backend,
    )


def test_valid_action_is_accepted() -> None:
    workspace = _workspace()

    result = _propose(workspace, [_action()])

    assert result["accepted"] == 1
    assert result["rejected"] == []
    action = workspace.remediation_actions[0]
    assert action.action_id == "act_001"
    assert action.hypothesis_id == "hyp_001"
    assert action.type == "code"
    assert action.evidence_ids == ["ev_0001"]
    assert action.target == CODE_TARGET


def test_action_can_cite_evidence_bound_to_its_hypothesis() -> None:
    workspace = _workspace()
    workspace.ledger.add(
        _evidence("ev_0004", "repo://OrderService.java#L10-L12")
    )
    workspace.ledger.bind(
        "ev_0004",
        "hyp_001",
        "hyp_001_req_01",
        tool_call_id="call_1",
    )

    result = _propose(workspace, [_action(evidence_ids=["ev_0004"])])

    assert result["accepted"] == 1
    assert workspace.remediation_actions[0].evidence_ids == ["ev_0004"]


def test_candidate_hypothesis_is_rejected() -> None:
    workspace = _workspace(status=HypothesisStatus.CANDIDATE)

    result = _propose(workspace, [_action()])

    assert result["accepted"] == 0
    assert workspace.remediation_actions == []
    assert workspace.rejected_remediations
    assert "supported/confirmed" in workspace.rejected_remediations[0].reason


def test_unknown_hypothesis_is_rejected() -> None:
    workspace = _workspace()

    result = _propose(workspace, [_action(hypothesis_id="hyp_999")])

    assert result["accepted"] == 0
    assert "does not exist" in workspace.rejected_remediations[0].reason


def test_missing_and_unassociated_evidence_are_rejected() -> None:
    workspace = _workspace()

    missing = _propose(
        workspace,
        [_action(evidence_ids=["ev_9999"])],
    )
    unassociated = _propose(
        workspace,
        [_action(evidence_ids=["ev_0002"])],
    )

    assert missing["accepted"] == 0
    assert unassociated["accepted"] == 0
    assert "does not exist" in workspace.rejected_remediations[0].reason
    assert "not associated with the hypothesis" in (
        workspace.rejected_remediations[1].reason
    )


def test_source_ref_must_resolve_to_associated_evidence() -> None:
    workspace = _workspace()

    accepted = _propose(
        workspace,
        [
            _action(
                evidence_ids=[],
                evidence_source_refs=["log://evt_0001"],
            )
        ],
    )
    rejected = _propose(
        workspace,
        [
            _action(
                evidence_ids=[],
                evidence_source_refs=["log://evt_0002"],
            )
        ],
    )

    assert accepted["accepted"] == 1
    assert workspace.remediation_actions[0].evidence_ids == ["ev_0001"]
    assert rejected["accepted"] == 0
    assert "not associated with the hypothesis" in (
        workspace.rejected_remediations[-1].reason
    )


def test_assessment_evidence_can_ground_an_action() -> None:
    workspace = _workspace()
    workspace.assessments.append(
        EvidenceAssessment(
            assessment_id="asm_0001",
            hypothesis_id="hyp_001",
            requirement_id="hyp_001_req_01",
            evidence_id="ev_0002",
            verdict=AssessmentVerdict.SUPPORTS,
            rationale="Corroborating log event.",
            created_at=CREATED_AT,
        )
    )

    result = _propose(workspace, [_action(evidence_ids=["ev_0002"])])

    assert result["accepted"] == 1
    assert workspace.remediation_actions[0].evidence_ids == ["ev_0002"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("type", "shell"),
        ("title", " "),
        ("description", ""),
        ("risk", ""),
        ("target", " "),
    ],
)
def test_invalid_fields_are_rejected(field: str, value: str) -> None:
    workspace = _workspace()

    result = _propose(workspace, [_action(**{field: value})])

    assert result["accepted"] == 0
    assert workspace.rejected_remediations


def test_code_target_must_be_inside_repo_and_exist() -> None:
    workspace = _workspace()

    outside = _propose(workspace, [_action(target="../Outside.java")])
    missing = _propose(
        workspace,
        [_action(target="src/main/java/com/example/order/Missing.java")],
    )

    assert outside["accepted"] == 0
    assert missing["accepted"] == 0
    assert "outside the repo" in workspace.rejected_remediations[0].reason
    assert "does not exist" in workspace.rejected_remediations[1].reason


def test_non_code_targets_are_not_file_verified() -> None:
    workspace = _workspace()

    result = _propose(
        workspace,
        [
            _action(type="ops", target="restart the order-service deployment"),
            _action(type="test", target="add a duplicate callback integration test"),
            _action(type="config", target="payment.callback.idempotent=true"),
        ],
    )

    assert result["accepted"] == 3
    assert [action.type for action in workspace.remediation_actions] == [
        "ops",
        "test",
        "config",
    ]


def test_data_target_requires_whitelisted_backend(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    workspace = _workspace()

    accepted = _propose(
        workspace,
        [
            _action(
                type="data",
                target="db://orders/id=10086",
                evidence_ids=["ev_0003"],
            )
        ],
        backend=backend,
    )
    rejected = _propose(
        _workspace(),
        [
            _action(
                type="data",
                target="db://payments/id=1",
                evidence_ids=["ev_0003"],
            )
        ],
        backend=backend,
    )
    no_backend = _propose(
        _workspace(),
        [
            _action(
                type="data",
                target="db://orders/id=10086",
                evidence_ids=["ev_0003"],
            )
        ],
    )

    assert accepted["accepted"] == 1
    assert rejected["accepted"] == 0
    assert no_backend["accepted"] == 0


def test_duplicate_actions_are_rejected() -> None:
    workspace = _workspace()

    result = _propose(workspace, [_action(), _action()])

    assert result["accepted"] == 1
    assert len(workspace.rejected_remediations) == 1
    assert "duplicate remediation action" in (
        workspace.rejected_remediations[0].reason
    )


def test_per_hypothesis_limit_is_enforced() -> None:
    workspace = _workspace()

    result = _propose(
        workspace,
        [
            _action(type="test", target="test one"),
            _action(type="test", target="test two"),
            _action(type="test", target="test three"),
            _action(type="test", target="test four"),
        ],
    )

    assert result["accepted"] == 3
    assert len(workspace.rejected_remediations) == 1
    assert "per-hypothesis action limit" in (
        workspace.rejected_remediations[0].reason
    )


def test_total_limit_is_enforced() -> None:
    workspace = _workspace(max_remediation_actions=1)

    result = _propose(
        workspace,
        [
            _action(type="test", target="test one"),
            _action(type="test", target="test two"),
        ],
    )

    assert result["accepted"] == 1
    assert "remediation action limit" in (
        workspace.rejected_remediations[0].reason
    )


def test_empty_proposal_is_a_protocol_error() -> None:
    workspace = _workspace()

    with pytest.raises(ProtocolError) as exc_info:
        _propose(workspace, [])

    assert exc_info.value.code == "INVALID_REMEDIATION"
