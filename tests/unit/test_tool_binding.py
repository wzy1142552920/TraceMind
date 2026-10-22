"""Unit tests for evidence tool metadata and control-tool auditing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

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
from tracemind.log_analysis.parser import LogParser
from tracemind.tools.builtin import build_default_registry
from tracemind.tools.contracts import (
    EvidenceToolMeta,
    ToolContext,
    ToolHandlerResult,
    ToolRequest,
    ToolSpec,
)
from tracemind.tools.executor import ToolExecutor
from tracemind.tools.registry import ToolRegistry
from tracemind.verification import load_verification_data

LOG_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "logs" / "basic" / "incident.log"
)


def _evidence(
    evidence_id: str,
    kind: EvidenceKind,
    source_ref: str,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        claim=f"{kind.value} claim",
        source_ref=source_ref,
        provenance=EvidenceProvenance.LOG_PARSER,
        observed_at="2026-10-22T00:00:00+00:00",
    )


def _workspace() -> DiagnosisWorkspace:
    ledger = EvidenceLedger()
    ledger.add(_evidence("ev_0001", EvidenceKind.LOG_EVENT, "log://evt_0001"))
    workspace = DiagnosisWorkspace(ledger)
    workspace.propose_hypothesis(
        HypothesisProposal(
            statement="zero rows means the order row is absent",
            cause_chain=["callback", "zero rows"],
            basis_evidence_ids=["ev_0001"],
            requirements=[
                RequirementProposal(
                    description="a second log event confirms zero rows",
                    evidence_kinds=[EvidenceKind.LOG_EVENT],
                    discriminating=True,
                )
            ],
            falsifiers=["the row exists"],
        )
    )
    return workspace


def _executor(workspace: DiagnosisWorkspace | None) -> ToolExecutor:
    parsed = LogParser().parse(LOG_FIXTURE)
    context = ToolContext(
        parsed_log=parsed,
        workspace=workspace,
        log_root=LOG_FIXTURE.parent,
    )
    return ToolExecutor(build_default_registry(), context)


def _request(
    tool_name: str,
    arguments: dict[str, object],
    tool_call_id: str = "call_1",
) -> ToolRequest:
    return ToolRequest(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        run_id="run_test",
    )


def test_bound_tool_result_and_audit_record_binding() -> None:
    workspace = _workspace()
    executor = _executor(workspace)

    result = executor.execute(
        _request(
            "logs.search",
            {
                "query": "rows=0",
                "hypothesis_id": "hyp_001",
                "requirement_id": "hyp_001_req_01",
            },
        )
    )

    assert result.ok
    assert result.bound_hypothesis_id == "hyp_001"
    assert result.bound_requirement_id == "hyp_001_req_01"
    audit = executor.audit_events[-1]
    assert audit.bound_hypothesis_id == "hyp_001"
    assert audit.bound_requirement_id == "hyp_001_req_01"
    assert audit.outcome == "allowed"


def test_binding_metadata_must_be_paired() -> None:
    executor = _executor(_workspace())

    result = executor.execute(
        _request(
            "logs.search",
            {"query": "rows=0", "hypothesis_id": "hyp_001"},
        )
    )

    assert not result.ok
    assert result.error_code == "INVALID_BINDING"
    assert executor.audit_events[-1].error_code == "INVALID_BINDING"


def test_binding_metadata_must_reference_real_objects() -> None:
    executor = _executor(_workspace())

    unknown_hypothesis = executor.execute(
        _request(
            "logs.search",
            {
                "query": "rows=0",
                "hypothesis_id": "hyp_999",
                "requirement_id": "hyp_001_req_01",
            },
            "call_1",
        )
    )
    unknown_requirement = executor.execute(
        _request(
            "logs.search",
            {
                "query": "rows=0",
                "hypothesis_id": "hyp_001",
                "requirement_id": "hyp_001_req_99",
            },
            "call_2",
        )
    )

    assert unknown_hypothesis.error_code == "INVALID_BINDING"
    assert unknown_requirement.error_code == "INVALID_BINDING"


def test_binding_metadata_without_workspace_is_rejected() -> None:
    executor = _executor(None)

    result = executor.execute(
        _request(
            "logs.search",
            {
                "query": "rows=0",
                "hypothesis_id": "hyp_001",
                "requirement_id": "hyp_001_req_01",
            },
        )
    )

    assert not result.ok
    assert result.error_code == "INVALID_BINDING"


def test_unbound_evidence_cannot_be_assessed() -> None:
    workspace = _workspace()
    executor = _executor(workspace)
    result = executor.execute(
        _request("logs.search", {"query": "rows=0"})
    )
    assert result.ok
    assert result.bound_hypothesis_id is None

    workspace.ledger.add(
        _evidence("ev_0002", EvidenceKind.LOG_EVENT, "log://evt_0002")
    )

    with pytest.raises(ProtocolError) as exc:
        workspace.assess_evidence(
            AssessmentsProposal(
                assessments=[
                    AssessmentProposal(
                        hypothesis_id="hyp_001",
                        requirement_id="hyp_001_req_01",
                        evidence_id="ev_0002",
                        verdict=AssessmentVerdict.SUPPORTS,
                        rationale="unbound evidence",
                    )
                ]
            )
        )
    assert exc.value.code == "INVALID_ASSESSMENT"


def test_control_tools_are_audited_and_assign_ids() -> None:
    workspace = DiagnosisWorkspace(
        EvidenceLedger(
            max_content_bytes=32768,
        )
    )
    workspace.ledger.add(
        _evidence("ev_0001", EvidenceKind.LOG_EVENT, "log://evt_0001")
    )
    executor = _executor(workspace)
    ledger_size = len(workspace.ledger)

    result = executor.execute(
        _request(
            "diagnosis.propose_hypothesis",
            {
                "statement": "zero rows means the order row is absent",
                "cause_chain": ["callback", "zero rows"],
                "basis_evidence_ids": ["ev_0001"],
                "requirements": [
                    {
                        "description": "row missing",
                        "evidence_kinds": ["db_row"],
                        "discriminating": True,
                    }
                ],
                "falsifiers": ["the row exists"],
            },
        )
    )

    assert result.ok
    assert result.data["hypothesis_id"] == "hyp_001"
    assert workspace.get_hypothesis("hyp_001") is not None
    assert len(workspace.ledger) == ledger_size
    assert executor.audit_events[-1].tool_name == "diagnosis.propose_hypothesis"
    assert executor.audit_events[-1].outcome == "allowed"


def test_control_tool_protocol_error_uses_stable_code() -> None:
    workspace = DiagnosisWorkspace()
    workspace.ledger.add(
        _evidence("ev_0001", EvidenceKind.LOG_EVENT, "log://evt_0001")
    )
    executor = _executor(workspace)

    result = executor.execute(
        _request(
            "diagnosis.propose_hypothesis",
            {
                "statement": "grounded statement",
                "cause_chain": ["one"],
                "basis_evidence_ids": ["ev_9999"],
                "requirements": [
                    {
                        "description": "row missing",
                        "evidence_kinds": ["db_row"],
                        "discriminating": True,
                    }
                ],
                "falsifiers": ["the row exists"],
            },
        )
    )

    assert not result.ok
    assert result.error_code == "HYPOTHESIS_NOT_GROUNDED"
    assert "ev_9999" in (result.error_message or "")
    assert executor.audit_events[-1].error_code == "HYPOTHESIS_NOT_GROUNDED"


def test_control_tool_rejects_runtime_fields() -> None:
    executor = _executor(DiagnosisWorkspace())

    result = executor.execute(
        _request(
            "diagnosis.propose_hypothesis",
            {
                "statement": "grounded statement",
                "cause_chain": ["one"],
                "basis_evidence_ids": ["ev_0001"],
                "requirements": [
                    {
                        "description": "row missing",
                        "evidence_kinds": ["db_row"],
                        "discriminating": True,
                    }
                ],
                "falsifiers": ["the row exists"],
                "hypothesis_id": "hyp_999",
            },
        )
    )

    assert not result.ok
    assert result.error_code == "INVALID_ARGUMENTS"


def test_db_binding_metadata_is_validated_and_attached(tmp_path: Path) -> None:
    data_path = tmp_path / "verification.json"
    data_path.write_text(
        json.dumps(
            {
                "backend": "fake",
                "tables": {
                    "orders": {
                        "primary_key": "id",
                        "columns": ["id", "status"],
                        "rows": [{"id": 10086, "status": "PAID"}],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    backend = load_verification_data(data_path)
    workspace = _workspace()
    executor = ToolExecutor(
        build_default_registry(verification_backend=backend),
        ToolContext(workspace=workspace, verification_backend=backend),
    )

    result = executor.execute(
        _request(
            "db.get_row",
            {
                "table": "orders",
                "key_value": 10086,
                "hypothesis_id": "hyp_001",
                "requirement_id": "hyp_001_req_01",
            },
        )
    )

    assert result.ok
    assert result.bound_hypothesis_id == "hyp_001"
    assert result.bound_requirement_id == "hyp_001_req_01"
    audit = executor.audit_events[-1]
    assert audit.bound_hypothesis_id == "hyp_001"
    assert audit.bound_requirement_id == "hyp_001_req_01"
    assert audit.outcome == "allowed"


def test_custom_evidence_tool_meta_is_not_consumed_by_handler() -> None:
    class DemoArgs(EvidenceToolMeta):
        value: str = "x"

    def handler(
        context: ToolContext,
        args: BaseModel,
    ) -> ToolHandlerResult:
        demo = args
        assert demo.value == "x"
        return ToolHandlerResult(data={"value": demo.value})

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="demo.evidence",
            description="demo",
            input_model=DemoArgs,
        ),
        handler,
    )
    executor = ToolExecutor(registry, ToolContext(workspace=_workspace()))
    result = executor.execute(
        _request(
            "demo.evidence",
            {
                "value": "x",
                "hypothesis_id": "hyp_001",
                "requirement_id": "hyp_001_req_01",
            },
        )
    )

    assert result.ok
    assert result.bound_hypothesis_id == "hyp_001"
