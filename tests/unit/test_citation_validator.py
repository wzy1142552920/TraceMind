"""Unit tests for report citation and evidence validation."""

from __future__ import annotations

from pathlib import Path

from tracemind.diagnosis.evidence import Evidence, Hypothesis, RunResult
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
    hypothesis_status: str = "confirmed",
    hypothesis_evidence_ids: list[str] | None = None,
) -> RunResult:
    evidence = [
        Evidence(
            evidence_id="ev_0001",
            kind="source_code",
            claim="Source",
            source_ref=source_ref,
            supports=["hyp_001"],
            strength="strong",
            created_at=CREATED_AT,
        )
    ]
    hypothesis = Hypothesis(
        hypothesis_id="hyp_001",
        statement="Exception originates in OrderService",
        status=hypothesis_status,
        evidence_ids=hypothesis_evidence_ids or ["ev_0001"],
        missing_evidence=[],
    )
    return RunResult(
        incident_id="inc_test",
        run_id="run_test",
        service="order-service",
        state=RuntimeState.COMPLETED,
        stop_reason=StopReason.EVIDENCE_SUFFICIENT,
        hypotheses=[hypothesis],
        evidence=evidence,
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
        _result("log://evt_missing"),
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
