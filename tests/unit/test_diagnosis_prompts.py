"""Unit tests for bounded diagnosis prompt rendering."""

from __future__ import annotations

from tracemind.diagnosis.budget import Budget, BudgetUsage
from tracemind.diagnosis.evidence import (
    EvaluationResult,
    Evidence,
    EvidenceBinding,
    EvidenceKind,
    EvidenceProvenance,
    Hypothesis,
    HypothesisStatus,
)
from tracemind.diagnosis.prompts import (
    build_remediation_prompt,
    build_user_prompt,
)


def _evidence(
    evidence_id: str,
    kind: EvidenceKind,
    source_ref: str,
    *,
    claim: str,
    content: dict[str, object] | None = None,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        claim=claim,
        source_ref=source_ref,
        provenance=EvidenceProvenance.TOOL,
        tool_call_id="call_1",
        observed_at="2026-10-22T00:00:00+00:00",
        content=content or {},
    )


def _prompt(evidence: list[Evidence]) -> str:
    return build_user_prompt(
        service="order-service",
        primary=None,
        thread_context=None,
        evidence=evidence,
        hypotheses=[],
        assessments=[],
        evaluation=EvaluationResult(),
        tools=[],
        verification_environment="fixture",
        budget=Budget(),
        usage=BudgetUsage(),
        previous_observation=None,
    )


def test_prompt_exposes_source_text_and_sql_text() -> None:
    prompt = _prompt(
        [
            _evidence(
                "ev_0001",
                EvidenceKind.SOURCE_CODE,
                "repo://OrderMapper.java#L10-L14",
                claim="Source com.example.OrderMapper.updateStatus",
                content={
                    "file_path": "OrderMapper.java",
                    "start_line": 10,
                    "end_line": 14,
                    "text": (
                        '@Update("UPDATE orders SET status = #{status} '
                        'WHERE id = #{orderId}")\n'
                        "default int updateStatus(Long orderId, String status) {\n"
                        "    return 0;\n"
                        "}"
                    ),
                },
            ),
            _evidence(
                "ev_0002",
                EvidenceKind.SQL,
                "repo://OrderMapper.java#L10",
                claim="SQL UPDATE on orders",
                content={
                    "sql_text": (
                        "UPDATE orders SET status = #{status} "
                        "WHERE id = #{orderId}"
                    )
                },
            ),
        ]
    )

    assert "default int updateStatus" in prompt
    assert "return 0;" in prompt
    assert "UPDATE orders SET status" in prompt


def test_prompt_exposes_db_row_values_and_redactions() -> None:
    prompt = _prompt(
        [
            _evidence(
                "ev_0003",
                EvidenceKind.DB_ROW,
                "db://orders/id=10086",
                claim="Fixture row orders id=10086: found",
                content={
                    "table": "orders",
                    "key_column": "id",
                    "key_value": 10086,
                    "found": True,
                    "row": {"id": 10086, "status": "PAID"},
                    "redacted_columns": ["customer_email"],
                    "environment": "fixture",
                },
            )
        ]
    )

    assert "found=True" in prompt
    assert '"status": "PAID"' in prompt
    assert "redacted=customer_email" in prompt


def test_remediation_prompt_lists_evidence_allowed_for_each_hypothesis() -> None:
    basis = _evidence(
        "ev_0001",
        EvidenceKind.LOG_EVENT,
        "log://evt_0001",
        claim="rows=0",
    )
    bound = _evidence(
        "ev_0002",
        EvidenceKind.DB_ROW,
        "db://orders/id=10086",
        claim="row exists",
    )
    bound.bindings = [
        EvidenceBinding(
            hypothesis_id="hyp_001",
            requirement_id="hyp_001_req_01",
            tool_call_id="call_1",
        )
    ]
    hypothesis = Hypothesis(
        hypothesis_id="hyp_001",
        statement="the order row already has the target status",
        basis_evidence_ids=["ev_0001"],
        status=HypothesisStatus.CONFIRMED,
    )

    prompt = build_remediation_prompt(
        service="order-service",
        primary=None,
        evidence=[basis, bound],
        hypotheses=[hypothesis],
        assessments=[],
        evaluation=EvaluationResult(),
        tools=[],
        verification_environment="fixture",
        budget=Budget(),
    )

    assert "allowed_evidence: ev_0001, ev_0002" in prompt
    assert "Cite only evidence IDs listed in allowed_evidence" in prompt
    assert "Respect field limits" in prompt
