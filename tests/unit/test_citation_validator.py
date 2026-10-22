"""Unit tests for report citation, verification, and evidence validation."""

from __future__ import annotations

from pathlib import Path

from tracemind.diagnosis.evidence import (
    EvaluationResult,
    Evidence,
    Hypothesis,
    HypothesisEvaluation,
    RunResult,
)
from tracemind.diagnosis.report import build_report, validate_report
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
CREATED_AT = "2026-10-21T00:00:00+00:00"


def _result(
    source_ref: str,
    *,
    kind: str = "source_code",
    hypothesis_status: str = "confirmed",
    hypothesis_evidence_ids: list[str] | None = None,
    content: dict | None = None,
    provenance: str = "ast_index",
) -> RunResult:
    evidence = [
        Evidence(
            evidence_id="ev_0001",
            kind=kind,
            claim="Referenced evidence",
            source_ref=source_ref,
            strength="strong",
            provenance=provenance,
            observed_at=CREATED_AT,
            content=content or {},
        )
    ]
    cited = hypothesis_evidence_ids or ["ev_0001"]
    hypothesis = Hypothesis(
        hypothesis_id="hyp_001",
        statement="Exception originates in OrderService",
        status=hypothesis_status,
        basis_evidence_ids=cited,
        evidence_ids=cited,
        missing_requirement_ids=[],
    )
    evaluation = EvaluationResult(
        hypotheses=[
            HypothesisEvaluation(
                hypothesis_id="hyp_001",
                status=hypothesis_status,
                qualifies=hypothesis_status in {"supported", "confirmed"},
                supporting_evidence_ids=cited,
            )
        ],
        top_hypothesis_id="hyp_001",
        run_confirmed=hypothesis_status == "confirmed",
    )
    return RunResult(
        incident_id="inc_test",
        run_id="run_test",
        service="order-service",
        state=RuntimeState.COMPLETED,
        stop_reason=StopReason.EVIDENCE_SUFFICIENT,
        hypotheses=[hypothesis],
        evidence=evidence,
        evaluation=evaluation,
        budget_usage={"iterations": 1, "llm_calls": 1, "tool_calls": 1},
        events=[],
    )


def _parsed():
    return LogParser().parse(LOG_FIXTURE)


def test_invalid_repo_path_is_rejected() -> None:
    report = build_report(
        _result("repo://../etc/passwd#L1-L2"),
        _parsed(),
        REPO_FIXTURE,
    )

    assert report.validation.citations_valid is False
    assert report.validation.errors
    assert report.sources[0].verified is False
    assert report.status == "insufficient_data"


def test_invalid_repo_line_range_is_rejected() -> None:
    report = build_report(
        _result(
            "repo://src/main/java/com/example/order/OrderService.java#L1-L9999"
        ),
        _parsed(),
        REPO_FIXTURE,
    )

    assert report.validation.citations_valid is False
    assert report.sources[0].verified is False
    assert report.status == "insufficient_data"


def test_invalid_log_event_is_rejected() -> None:
    report = build_report(
        _result("log://evt_missing", kind="log_event", provenance="log_parser"),
        _parsed(),
        REPO_FIXTURE,
    )

    assert report.validation.citations_valid is False
    assert report.sources[0].verified is False
    assert report.status == "insufficient_data"


def test_missing_evidence_id_is_rejected() -> None:
    report = build_report(
        _result(
            "log://evt_0003",
            hypothesis_evidence_ids=["ev_0001", "ev_missing"],
        ),
        _parsed(),
        REPO_FIXTURE,
    )

    assert report.validation.citations_valid is True
    assert report.validation.evidence_ids_valid is False
    assert report.status == "insufficient_data"
    assert any("ev_missing" in error for error in report.validation.errors)


def test_status_inconsistency_is_downgraded() -> None:
    result = _result("log://evt_0003", hypothesis_status="supported")
    parsed = _parsed()
    report = build_report(result, parsed, REPO_FIXTURE)
    assert report.status == "probable"

    report.status = "confirmed"
    validate_report(report, result, parsed, REPO_FIXTURE)

    assert report.status == "probable"
    assert report.validation.status_consistent is False
    assert report.validation.citations_valid is True
    assert report.validation.evidence_ids_valid is True


def test_valid_log_file_reference() -> None:
    parsed = _parsed()
    file_ref = f"log://{Path(parsed.source_file).name}#L1-L2"

    report = build_report(_result(file_ref), parsed, REPO_FIXTURE)

    assert report.validation.citations_valid is True
    assert report.sources[0].verified is True


def test_valid_thread_context_reference() -> None:
    parsed = _parsed()
    file_ref = (
        f"log://{Path(parsed.source_file).name}"
        "#thread=http-nio-8080-exec-7&L1-L3"
    )

    report = build_report(
        _result(
            file_ref,
            kind="log_thread_context",
            provenance="log_parser",
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
        parsed,
        REPO_FIXTURE,
    )

    assert report.validation.citations_valid is True
    assert report.sources[0].verified is True
    assert report.sources[0].thread == "http-nio-8080-exec-7"
    assert report.sources[0].line_start == 1
    assert report.sources[0].messages[0] == "paid callback orderId=10086"


def test_thread_context_requires_matching_ledger_evidence() -> None:
    parsed = _parsed()
    file_ref = (
        f"log://{Path(parsed.source_file).name}"
        "#thread=http-nio-9999-exec-1&L1-L3"
    )

    report = build_report(
        _result(
            file_ref,
            kind="log_thread_context",
            provenance="log_parser",
            content={
                "thread": "http-nio-8080-exec-7",
                "line_start": 1,
                "line_end": 3,
            },
        ),
        parsed,
        REPO_FIXTURE,
    )

    assert report.validation.citations_valid is False
    assert any(
        "same-thread context" in error for error in report.validation.errors
    )


def test_thread_context_range_outside_recorded_evidence_is_rejected() -> None:
    parsed = _parsed()
    file_ref = (
        f"log://{Path(parsed.source_file).name}"
        "#thread=http-nio-8080-exec-7&L1-L5"
    )

    report = build_report(
        _result(
            file_ref,
            kind="log_thread_context",
            provenance="log_parser",
            content={
                "thread": "http-nio-8080-exec-7",
                "line_start": 1,
                "line_end": 3,
            },
        ),
        parsed,
        REPO_FIXTURE,
    )

    assert report.validation.citations_valid is False
    assert any(
        "outside the recorded same-thread evidence" in error
        for error in report.validation.errors
    )


def test_valid_db_reference_and_fixture_labeling() -> None:
    report = build_report(
        _result(
            "db://orders/id=10086",
            kind="db_row",
            provenance="fake_verification",
            content={"table": "orders", "environment": "fixture"},
        ),
        _parsed(),
        REPO_FIXTURE,
    )

    assert report.validation.citations_valid is True
    assert report.validation.verification_labeled is True
    assert report.verification.environment == "fixture"
    assert report.verification.backend == "fake"
    assert report.verification.tables_queried == ["orders"]
    assert "fixture" in report.verification.note.lower()
    assert any("fixture" in item.lower() for item in report.limitations)


def test_db_reference_must_exist_in_ledger() -> None:
    parsed = _parsed()
    result = _result(
        "db://orders/id=10086",
        kind="db_row",
        provenance="fake_verification",
        content={"table": "orders", "environment": "fixture"},
    )
    report = build_report(result, parsed, REPO_FIXTURE)
    report.sources[0].source_ref = "db://orders/id=99999"

    validate_report(report, result, parsed, REPO_FIXTURE)

    assert report.validation.citations_valid is False
    assert any(
        "not present in the evidence ledger" in error
        for error in report.validation.errors
    )


def test_fixture_labeling_failure_is_reported_without_downgrade() -> None:
    parsed = _parsed()
    result = _result(
        "db://orders/id=10086",
        kind="db_row",
        provenance="fake_verification",
        content={"table": "orders", "environment": "fixture"},
    )
    report = build_report(result, parsed, REPO_FIXTURE)
    report.verification.environment = "none"
    report.verification.note = ""

    validate_report(report, result, parsed, REPO_FIXTURE)

    assert report.validation.verification_labeled is False
    assert report.validation.remediation_grounded is True
    assert report.status == "confirmed"
    assert any(
        "verification.environment must be fixture" in error
        for error in report.validation.errors
    )


def test_valid_single_line_repo_reference() -> None:
    report = build_report(
        _result(
            "repo://src/main/java/com/example/order/OrderMapper.java#L16"
        ),
        _parsed(),
        REPO_FIXTURE,
    )

    assert report.validation.citations_valid is True
    assert report.sources[0].verified is True
