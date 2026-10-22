"""Unit tests for report generation and status mapping for schema 0.3."""

from __future__ import annotations

import json
from pathlib import Path

from tracemind.diagnosis.evidence import (
    EvaluationResult,
    Evidence,
    Hypothesis,
    HypothesisEvaluation,
    RunResult,
    ToolCallRecord,
)
from tracemind.diagnosis.report import build_report, render_markdown, report_status
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
SOURCE_REF = "repo://src/main/java/com/example/order/OrderService.java#L17-L27"


def _result(
    hypothesis_status: str = "confirmed",
    state: RuntimeState = RuntimeState.COMPLETED,
    stop: StopReason = StopReason.EVIDENCE_SUFFICIENT,
) -> RunResult:
    evidence = [
        Evidence(
            evidence_id="ev_0001",
            kind="stack_frame",
            claim="Stack frame",
            source_ref="log://evt_0003",
            strength="strong",
            provenance="log_parser",
            observed_at=CREATED_AT,
        ),
        Evidence(
            evidence_id="ev_0002",
            kind="log_event",
            claim="Primary log event",
            source_ref="log://evt_0003",
            strength="strong",
            provenance="log_parser",
            observed_at=CREATED_AT,
        ),
        Evidence(
            evidence_id="ev_0003",
            kind="source_code",
            claim="Source range",
            source_ref=SOURCE_REF,
            strength="strong",
            provenance="ast_index",
            tool_call_id="call_1",
            observed_at=CREATED_AT,
        ),
    ]
    hypothesis = Hypothesis(
        hypothesis_id="hyp_001",
        statement="Exception originates at OrderService.updateStatus",
        status=hypothesis_status,
        basis_evidence_ids=[item.evidence_id for item in evidence],
        evidence_ids=[item.evidence_id for item in evidence],
        missing_requirement_ids=[],
        ranking_score=5,
    )
    run_confirmed = (
        hypothesis_status == "confirmed" and state is not RuntimeState.FAILED
    )
    evaluation = EvaluationResult(
        hypotheses=[
            HypothesisEvaluation(
                hypothesis_id="hyp_001",
                status=hypothesis_status,
                qualifies=hypothesis_status in {"supported", "confirmed"},
                supporting_evidence_ids=[item.evidence_id for item in evidence],
                ranking_score=5,
            )
        ],
        top_hypothesis_id="hyp_001",
        run_confirmed=run_confirmed,
    )
    return RunResult(
        incident_id="inc_test",
        run_id="run_test",
        service="order-service",
        state=state,
        stop_reason=stop,
        hypotheses=[hypothesis],
        evidence=evidence,
        evaluation=evaluation,
        tool_calls=[
            ToolCallRecord(
                tool_call_id="call_1",
                tool_name="code.find_symbol",
                arguments={"query": "OrderService.updateStatus"},
                ok=True,
                duration_ms=3,
                evidence_ids=["ev_0003"],
            )
        ],
        budget_usage={"iterations": 1, "llm_calls": 1, "tool_calls": 1},
        limitations=["fixture limitation"],
        events=[],
    )


def test_report_status_mapping() -> None:
    assert report_status(_result("confirmed")) == "confirmed"
    assert report_status(_result("supported")) == "probable"
    assert (
        report_status(
            _result(
                "candidate",
                state=RuntimeState.INSUFFICIENT_DATA,
                stop=StopReason.NO_PROGRESS,
            )
        )
        == "insufficient_data"
    )
    assert (
        report_status(
            _result(
                "supported",
                state=RuntimeState.STOPPED_BUDGET,
                stop=StopReason.BUDGET_EXHAUSTED,
            )
        )
        == "probable"
    )
    assert (
        report_status(
            _result(
                "supported",
                state=RuntimeState.FAILED,
                stop=StopReason.ERROR,
            )
        )
        == "insufficient_data"
    )


def test_build_confirmed_report() -> None:
    parsed = LogParser().parse(LOG_FIXTURE)
    report = build_report(_result(), parsed, REPO_FIXTURE)

    assert report.schema_version == "0.3"
    assert report.status == "confirmed"
    assert report.incident_id == "inc_test"
    assert report.run_id == "run_test"
    assert report.hypotheses
    hypothesis = report.hypotheses[0]
    assert hypothesis.hypothesis_id == "hyp_001"
    assert hypothesis.status == "confirmed"
    assert hypothesis.ranking_score == 5
    assert set(source.source_ref for source in report.sources) == {
        "log://evt_0003",
        SOURCE_REF,
    }
    assert report.sources
    assert all(source.verified for source in report.sources)
    assert report.verification.environment == "none"
    assert report.stop.state == "COMPLETED"
    assert report.stop.reason == "evidence_sufficient"
    assert report.budget_usage["tool_calls"] == 1
    assert report.validation.citations_valid is True
    assert report.validation.evidence_ids_valid is True
    assert report.validation.hypotheses_valid is True
    assert report.validation.remediation_grounded is True
    assert report.validation.verification_labeled is True
    assert report.validation.status_consistent is True


def test_report_json_and_markdown() -> None:
    parsed = LogParser().parse(LOG_FIXTURE)
    report = build_report(_result(), parsed, REPO_FIXTURE)

    data = json.loads(report.model_dump_json())
    assert data["schema_version"] == "0.3"
    assert "root_causes" not in data
    assert data["validation"]["hypotheses_valid"] is True

    markdown = render_markdown(report)
    assert "# TraceMind 诊断报告" in markdown
    assert "## 鉴别诊断" in markdown
    assert "## 验证过程" in markdown
    assert "## 修复方案" in markdown
    assert "## 证据来源" in markdown
    assert "OrderService.java" in markdown
    assert "## 工具调用" in markdown
    assert "## LLM 使用" in markdown


def test_markdown_template_handles_empty_sections() -> None:
    result = RunResult(
        incident_id="inc_empty",
        run_id="run_empty",
        service="order-service",
        state=RuntimeState.INSUFFICIENT_DATA,
        stop_reason=StopReason.NO_PROGRESS,
        budget_usage={"iterations": 0, "llm_calls": 0, "tool_calls": 0},
    )

    report = build_report(result, LogParser().parse(LOG_FIXTURE), REPO_FIXTURE)
    markdown = render_markdown(report)

    assert report.status == "insufficient_data"
    assert "No supported root cause candidate was produced." in markdown
    assert "无假设。" in markdown
    assert "- （无）" in markdown
    assert "citations_valid: True" in markdown
