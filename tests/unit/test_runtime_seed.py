"""Unit tests for seed hypotheses and seed evidence."""

from __future__ import annotations

from pathlib import Path

from tracemind.diagnosis.runtime import DiagnosisRuntime
from tracemind.diagnosis.state import RuntimeState, StopReason
from tracemind.indexing.java_index import TreeSitterJavaIndex
from tracemind.llm.mock import MockProvider
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


def _index() -> TreeSitterJavaIndex:
    index = TreeSitterJavaIndex()
    index.index(REPO_FIXTURE)
    return index


def test_no_in_project_frame_returns_insufficient_data(tmp_path: Path) -> None:
    log_path = tmp_path / "jdk-only.log"
    log_path.write_text(
        "2026-10-18 10:21:03.416 ERROR [t] c.e.X - boom\n"
        "java.lang.IllegalStateException: boom\n"
        "    at java.base/java.lang.Thread.run(Thread.java:840)\n",
        encoding="utf-8",
    )
    parsed = LogParser().parse(log_path)
    runtime = DiagnosisRuntime(repo_root=REPO_FIXTURE)

    result = runtime.run(
        parsed,
        _index(),
        "order-service",
        MockProvider([]),
    )

    assert result.state is RuntimeState.INSUFFICIENT_DATA
    assert result.stop_reason is StopReason.NO_PROGRESS
    assert result.budget_usage == {
        "iterations": 0,
        "llm_calls": 0,
        "tool_calls": 0,
    }
    assert len(result.hypotheses) == 1
    assert result.hypotheses[0].status == "insufficient_data"
    assert result.hypotheses[0].source_matches == []
    assert all(item.kind != "source_code" for item in result.evidence)
    assert result.tool_calls == []


def test_seed_evidence_without_tool_calls() -> None:
    parsed = LogParser().parse(LOG_FIXTURE)
    runtime = DiagnosisRuntime(repo_root=REPO_FIXTURE)

    result = runtime.run(
        parsed,
        _index(),
        "order-service",
        MockProvider([]),
    )

    assert result.state is RuntimeState.INSUFFICIENT_DATA
    assert result.stop_reason is StopReason.NO_PROGRESS
    assert result.budget_usage["iterations"] == 1
    assert result.budget_usage["llm_calls"] == 1
    assert result.budget_usage["tool_calls"] == 0

    hypothesis = result.hypotheses[0]
    assert hypothesis.status == "supported"
    assert hypothesis.missing_evidence == ["source_code"]
    assert "OrderService.updateStatus" in hypothesis.statement
    assert hypothesis.source_matches
    assert hypothesis.evidence_ids

    kinds = {item.kind for item in result.evidence}
    assert {"stack_frame", "log_event"} <= kinds
    assert "source_code" not in kinds
