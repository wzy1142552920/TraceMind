"""Unit tests for report generation and status mapping."""

from __future__ import annotations

import json
from pathlib import Path

from tracemind.diagnosis.evidence import (
    Evidence,
    Hypothesis,
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
            supports=["hyp_001"],
            strength="strong",
            created_at=CREATED_AT,
        ),
        Evidence(
            evidence_id="ev_0002",
            kind="log_event",
            claim="Primary log event",
            source_ref="log://evt_0003",
            supports=["hyp_001"],
            strength="strong",
            created_at=CREATED_AT,
        ),
        Evidence(
            evidence_id="ev_0003",
            kind="source_code",
            claim="Source range",
            source_ref=SOURCE_REF,
            supports=["hyp_001"],
            strength="strong",
            tool_call_id="call_1",
            created_at=CREATED_AT,
        ),
    ]
    hypothesis = Hypothesis(
        hypothesis_id="hyp_001",
        statement="Exception originates at OrderService.updateStatus",
        status=hypothesis_status,
        evidence_ids=[item.evidence_id for item in evidence],
        missing_evidence=[],
    )
    return RunResult(
        incident_id="inc_test",
        run_id="run_test",
        service="order-service",
        state=state,
        stop_reason=stop,
        hypotheses=[hypothesis],
        evidence=evidence,
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

    assert report.schema_version == "0.1"
    assert report.status == "confirmed"
    assert report.incident_id == "inc_test"
    assert report.run_id == "run_test"
    assert report.root_causes
    root = report.root_causes[0]
    assert root.hypothesis_id == "hyp_001"
    assert root.source_refs == ["log://evt_0003", SOURCE_REF]
    assert report.sources
    assert all(source.verified for source in report.sources)
    assert report.stop.state == "COMPLETED"
    assert report.stop.reason == "evidence_sufficient"
    assert report.budget_usage["tool_calls"] == 1
    assert report.validation.citations_valid is True
    assert report.validation.evidence_ids_valid is True
    assert report.validation.status_consistent is True


def test_report_json_and_markdown() -> None:
    parsed = LogParser().parse(LOG_FIXTURE)
    report = build_report(_result(), parsed, REPO_FIXTURE)

    data = json.loads(report.model_dump_json())
    assert data["schema_version"] == "0.1"
    assert data["validation"]["citations_valid"] is True

    markdown = render_markdown(report)
    assert "# TraceMind 诊断报告" in markdown
    assert "## 根因候选" in markdown
    assert "## 证据来源" in markdown
    assert "OrderService.java" in markdown
    assert "## 工具调用" in markdown


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

    assert "无支持的根因候选。" in markdown
    assert "- （无）" in markdown
    assert "citations_valid: True" in markdown
