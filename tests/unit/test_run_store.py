"""Unit tests for run-directory persistence."""

from __future__ import annotations

import json
from pathlib import Path

from tracemind.diagnosis.evidence import (
    Evidence,
    Hypothesis,
    RunResult,
    ToolCallRecord,
)
from tracemind.diagnosis.report import build_report
from tracemind.diagnosis.state import RuntimeEvent, RuntimeState, StopReason
from tracemind.log_analysis.parser import LogParser
from tracemind.storage.run_store import RunStore

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


def _result(run_id: str = "run_test") -> RunResult:
    evidence = [
        Evidence(
            evidence_id="ev_0001",
            kind="source_code",
            claim="Source range",
            source_ref=(
                "repo://src/main/java/com/example/order/OrderService.java#L17-L27"
            ),
            supports=["hyp_001"],
            strength="strong",
            created_at=CREATED_AT,
        )
    ]
    return RunResult(
        incident_id="inc_test",
        run_id=run_id,
        service="order-service",
        state=RuntimeState.COMPLETED,
        stop_reason=StopReason.EVIDENCE_SUFFICIENT,
        hypotheses=[
            Hypothesis(
                hypothesis_id="hyp_001",
                statement="Exception originates in OrderService",
                status="confirmed",
                evidence_ids=["ev_0001"],
                missing_evidence=[],
            )
        ],
        evidence=evidence,
        tool_calls=[
            ToolCallRecord(
                tool_call_id="call_1",
                tool_name="code.find_symbol",
                arguments={"query": "OrderService.updateStatus"},
                ok=True,
                duration_ms=3,
                evidence_ids=["ev_0001"],
            )
        ],
        budget_usage={"iterations": 1, "llm_calls": 1, "tool_calls": 1},
        events=[
            RuntimeEvent(
                event_type="diagnosis.started",
                timestamp="2026-10-21T00:00:00+00:00",
                data={"run_id": run_id},
            )
        ],
    )


def _meta(result: RunResult) -> dict[str, object]:
    return {
        "run_id": result.run_id,
        "incident_id": result.incident_id,
        "service": result.service,
        "provider": "mock",
        "model": "script",
        "log_path": str(LOG_FIXTURE),
        "repo_path": str(REPO_FIXTURE),
        "state": result.state.value,
        "stop_reason": result.stop_reason.value,
        "budget_usage": result.budget_usage,
    }


def test_write_all_run_artifacts(tmp_path: Path) -> None:
    result = _result()
    parsed = LogParser().parse(LOG_FIXTURE)
    report = build_report(result, parsed, REPO_FIXTURE)
    store = RunStore(tmp_path / "runs")

    run_dir = store.write(result, report, _meta(result))

    assert run_dir.name == result.run_id
    assert {path.name for path in run_dir.iterdir()} == {
        "run.json",
        "events.jsonl",
        "audit.jsonl",
        "report.md",
        "report.json",
    }

    run_text = (run_dir / "run.json").read_text(encoding="utf-8")
    run_data = json.loads(run_text)
    assert run_data["provider"] == "mock"
    assert "DEEPSEEK_API_KEY" not in run_text
    assert "sk-" not in run_text

    report_data = json.loads(
        (run_dir / "report.json").read_text(encoding="utf-8")
    )
    assert report_data["run_id"] == result.run_id
    assert report_data["validation"]["citations_valid"] is True

    event_lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event_type"] for line in event_lines] == [
        "diagnosis.started"
    ]

    audit_lines = (run_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    audit = [json.loads(line) for line in audit_lines]
    assert len(audit) == 1
    assert audit[0]["tool_call_id"] == "call_1"
    assert len(audit[0]["args_hash"]) == 64

    markdown = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "# TraceMind 诊断报告" in markdown


def test_repeated_runs_use_distinct_directories(tmp_path: Path) -> None:
    parsed = LogParser().parse(LOG_FIXTURE)
    store = RunStore(tmp_path / "runs")

    first = _result("run_001")
    first_report = build_report(first, parsed, REPO_FIXTURE)
    first_dir = store.write(first, first_report, _meta(first))

    second = _result("run_002")
    second_report = build_report(second, parsed, REPO_FIXTURE)
    second_dir = store.write(second, second_report, _meta(second))

    assert first_dir != second_dir
    assert first_dir.exists()
    assert second_dir.exists()
