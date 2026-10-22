"""Unit tests for runtime-created initial evidence."""

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


def test_no_in_project_frame_still_plans_but_has_no_source(
    tmp_path: Path,
) -> None:
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
    assert result.budget_usage["iterations"] == 3
    assert result.budget_usage["llm_calls"] == 3
    assert result.budget_usage["tool_calls"] == 0
    assert result.hypotheses == []
    kinds = {item.kind for item in result.evidence}
    assert kinds == {"log_event", "log_thread_context"}
    assert all(item.kind != "stack_frame" for item in result.evidence)
    assert all(item.kind != "source_code" for item in result.evidence)
    assert result.tool_calls == []


def test_initial_evidence_without_tool_calls() -> None:
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
    assert result.budget_usage["iterations"] == 3
    assert result.budget_usage["llm_calls"] == 3
    assert result.budget_usage["tool_calls"] == 0
    assert result.hypotheses == []

    by_kind = {item.kind: item for item in result.evidence}
    assert set(by_kind) == {
        "log_event",
        "log_thread_context",
        "stack_frame",
        "source_code",
    }
    context = by_kind["log_thread_context"]
    assert context.provenance == "log_parser"
    assert context.bound_hypothesis_id is None
    assert context.source_ref == (
        "log://incident.log#thread=http-nio-8080-exec-7&L1-L3"
    )
    assert context.content["items"]
    assert all(
        item["logger_class"]
        for item in context.content["items"]
    )
    assert "OrderService.updateStatus" in by_kind["stack_frame"].claim
    assert by_kind["source_code"].provenance == "ast_index"
    assert by_kind["source_code"].source_ref.endswith(
        "OrderService.java#L17-L27"
    )
